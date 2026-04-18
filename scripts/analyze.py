#!/usr/bin/env python3
"""
Automatic analyzer for ROS2 middleware benchmark results.

Reads all CSV files from results/ directory, computes statistics,
generates comparison tables and plots.

Usage:
    python3 scripts/analyze.py
    python3 scripts/analyze.py --results-dir results/
    python3 scripts/analyze.py --no-plots       # tables only
"""

import argparse
import csv
import statistics
import os
from pathlib import Path
from collections import defaultdict

try:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    HAS_MATPLOTLIB = True
except ImportError:
    HAS_MATPLOTLIB = False
    print("WARNING: matplotlib not found, skipping plots. Install with: pip3 install matplotlib")


def parse_experiment_dir(dirpath):
    name = dirpath.name
    parts = name.split('_')
    if len(parts) < 3 or not parts[-1].endswith('nodes'):
        return None
    topology = parts[0]
    profile = '_'.join(parts[1:-1])
    num_nodes = int(parts[-1].replace('nodes', ''))
    middleware = dirpath.parent.name
    return {
        'middleware': middleware,
        'topology': topology,
        'profile': profile,
        'num_nodes': num_nodes,
        'path': dirpath,
    }


def analyze_subscriber_csv(filepath):
    records = []
    with open(filepath, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            records.append(row)

    if not records:
        return None

    data = [r for r in records if r['is_warmup'] == '0']
    warmup = [r for r in records if r['is_warmup'] == '1']

    if not data:
        return None

    publish_overheads = [int(r['publish_overhead_ns']) / 1000 for r in data]
    delivery_times = [int(r['delivery_ns']) / 1000 for r in data]
    latencies_ns = [int(r['latency_ns']) for r in data]
    latencies_us = [l / 1000 for l in latencies_ns]
    discovery_ns = int(records[0]['discovery_time_ns'])

    sorted_lat = sorted(latencies_us)
    n = len(sorted_lat)

    return {
        'publish_overhead_us': publish_overheads,
        'delivery_us': delivery_times,
        'publish_overhead_mean_us': statistics.mean(publish_overheads),
        'publish_overhead_median_us': statistics.median(publish_overheads),
        'delivery_mean_us': statistics.mean(delivery_times),
        'delivery_median_us': statistics.median(delivery_times),
        'subscriber_id': int(data[0]['subscriber_id']),
        'total_records': len(records),
        'warmup_count': len(warmup),
        'data_count': len(data),
        'discovery_ms': discovery_ns / 1e6,
        'mean_us': statistics.mean(latencies_us),
        'median_us': statistics.median(latencies_us),
        'stddev_us': statistics.stdev(latencies_us) if len(latencies_us) > 1 else 0,
        'min_us': min(latencies_us),
        'max_us': max(latencies_us),
        'p50_us': sorted_lat[int(n * 0.50)],
        'p90_us': sorted_lat[int(n * 0.90)],
        'p95_us': sorted_lat[int(n * 0.95)],
        'p99_us': sorted_lat[int(n * 0.99)],
        'latencies_us': latencies_us,
    }


def analyze_docker_stats(filepath):
    if not filepath.exists():
        return None
    cpu_by_container = defaultdict(list)
    mem_by_container = defaultdict(list)
    with open(filepath, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                name = row['container']
                cpu = float(row['cpu_percent'].replace('%', ''))
                mem_str = row['mem_usage_mb'].split('/')[0].strip()
                mem = float(mem_str.replace('MiB', '').replace('GiB', ''))
                if 'GiB' in row['mem_usage_mb'].split('/')[0]:
                    mem *= 1024
                cpu_by_container[name].append(cpu)
                mem_by_container[name].append(mem)
            except (ValueError, KeyError):
                continue
    total_cpu_avg = sum(statistics.mean(v) for v in cpu_by_container.values())
    total_mem_avg = sum(statistics.mean(v) for v in mem_by_container.values())
    return {
        'total_cpu_avg_pct': total_cpu_avg,
        'total_mem_avg_mib': total_mem_avg,
        'num_containers': len(cpu_by_container),
    }


def analyze_experiment(exp_info):
    dirpath = exp_info['path']
    csv_files = sorted(dirpath.glob("sub_*.csv"))
    if not csv_files:
        return None

    sub_results = []
    all_latencies = []
    all_publish = []
    all_delivery = []

    for f in csv_files:
        result = analyze_subscriber_csv(f)
        if result:
            sub_results.append(result)
            all_latencies.extend(result['latencies_us'])
            pub = result.get('publish_overhead_us')
            deliv = result.get('delivery_us')
            if pub is not None and deliv is not None:
                all_publish.extend(pub)
                all_delivery.extend(deliv)

    if not all_latencies:
        return None

    sorted_all = sorted(all_latencies)
    n = len(sorted_all)

    docker_stats = analyze_docker_stats(dirpath / "docker_stats.csv")
    discovery_times = [s['discovery_ms'] for s in sub_results]

    pub_ovh_median = statistics.median(all_publish) if all_publish else 0
    pub_ovh_mean = statistics.mean(all_publish) if all_publish else 0
    deliv_median = statistics.median(all_delivery) if all_delivery else 0
    deliv_mean = statistics.mean(all_delivery) if all_delivery else 0

    return {
        **exp_info,
        'num_subscribers_actual': len(sub_results),
        'total_messages': len(all_latencies),
        'aggregate': {
            'publish_overhead_mean_us': pub_ovh_mean,
            'publish_overhead_median_us': pub_ovh_median,
            'delivery_mean_us': deliv_mean,
            'delivery_median_us': deliv_median,
            'mean_us': statistics.mean(all_latencies),
            'median_us': statistics.median(all_latencies),
            'stddev_us': statistics.stdev(all_latencies) if len(all_latencies) > 1 else 0,
            'min_us': min(all_latencies),
            'max_us': max(all_latencies),
            'p90_us': sorted_all[int(n * 0.90)],
            'p95_us': sorted_all[int(n * 0.95)],
            'p99_us': sorted_all[int(n * 0.99)],
        },
        'discovery': {
            'min_ms': min(discovery_times),
            'max_ms': max(discovery_times),
            'mean_ms': statistics.mean(discovery_times),
        },
        'docker_stats': docker_stats,
        'subscribers': sub_results,
    }


def print_scaling_table(experiments, profile="imu"):
    by_mw = defaultdict(list)
    for exp in experiments:
        if exp and exp['profile'] == profile:
            by_mw[exp['middleware']].append(exp)

    for mw in sorted(by_mw.keys()):
        exps = sorted(by_mw[mw], key=lambda x: x['num_nodes'])
        print(f"\n{'='*95}")
        print(f"  SCALING: {mw.upper()} | profile={profile} | fan-out")
        print(f"{'='*95}")
        print(f"  {'Nodes':>6} {'Subs':>5} {'Median':>10} {'Mean':>10} {'P95':>10} "
              f"{'P99':>10} {'PubOvh':>10} {'Delivery':>10} {'Disc.':>8} {'CPU':>8}")
        print(f"  {'':>6} {'':>5} {'(us)':>10} {'(us)':>10} {'(us)':>10} "
              f"{'(us)':>10} {'(us)':>10} {'(us)':>10} {'(ms)':>8} {'(%)':>8}")
        print(f"  {'-'*90}")

        for exp in exps:
            a = exp['aggregate']
            d = exp['discovery']
            cpu = exp['docker_stats']['total_cpu_avg_pct'] if exp['docker_stats'] else 0
            print(f"  {exp['num_nodes']:>6} {exp['num_subscribers_actual']:>5} "
                  f"{a['median_us']:>10.1f} {a['mean_us']:>10.1f} "
                  f"{a['p95_us']:>10.1f} {a['p99_us']:>10.1f} "
                  f"{a['publish_overhead_median_us']:>10.1f} {a['delivery_median_us']:>10.1f} "
                  f"{d['mean_ms']:>8.0f} {cpu:>8.1f}")

    print(f"  {'='*90}")


def print_comparison_table(experiments, profile="imu"):
    by_mw_nodes = {}
    for exp in experiments:
        if exp and exp['profile'] == profile:
            key = (exp['middleware'], exp['num_nodes'])
            by_mw_nodes[key] = exp

    all_nodes = sorted(set(n for _, n in by_mw_nodes.keys()))
    middlewares = sorted(set(mw for mw, _ in by_mw_nodes.keys()))

    if len(middlewares) < 2:
        return

    print(f"\n{'='*80}")
    print(f"  HEAD-TO-HEAD: CycloneDDS vs Zenoh | profile={profile}")
    print(f"{'='*80}")
    print(f"  {'Nodes':>6} |  {'CycloneDDS':^30}  |  {'Zenoh':^30}")
    print(f"  {'':>6} |  {'Med(us)':>10} {'P95(us)':>10} {'Disc(ms)':>10} "
          f"|  {'Med(us)':>10} {'P95(us)':>10} {'Disc(ms)':>10}")
    print(f"  {'-'*74}")

    for n in all_nodes:
        parts = []
        for mw in middlewares:
            key = (mw, n)
            if key in by_mw_nodes:
                exp = by_mw_nodes[key]
                a = exp['aggregate']
                d = exp['discovery']
                parts.append(f"{a['median_us']:>10.1f} {a['p95_us']:>10.1f} {d['mean_ms']:>10.0f}")
            else:
                parts.append(f"{'--':>10} {'--':>10} {'--':>10}")
        print(f"  {n:>6} |  {parts[0]}  |  {parts[1] if len(parts) > 1 else ''}")

    print(f"  {'='*74}")


def generate_plots(experiments, output_dir):
    if not HAS_MATPLOTLIB:
        return

    plots_dir = output_dir / "plots"
    plots_dir.mkdir(exist_ok=True)

    by_mw_profile = defaultdict(list)
    for exp in experiments:
        if exp:
            by_mw_profile[(exp['middleware'], exp['profile'])].append(exp)

    profiles = sorted(set(exp['profile'] for exp in experiments if exp))

    for profile in profiles:
        fig, axes = plt.subplots(3, 2, figsize=(14, 15))
        fig.suptitle(f'ROS2 Middleware Scaling Benchmark: {profile} profile', fontsize=14, fontweight='bold')

        middlewares_in_data = sorted(set(
            exp['middleware'] for exp in experiments
            if exp and exp['profile'] == profile
        ))

        colors = {'cyclonedds': '#2196F3', 'zenoh': '#4CAF50'}
        markers = {'cyclonedds': 'o', 'zenoh': 's'}

        for mw in middlewares_in_data:
            exps = sorted(by_mw_profile[(mw, profile)], key=lambda x: x['num_nodes'])
            nodes = [e['num_nodes'] for e in exps]
            color = colors.get(mw, '#999999')
            marker = markers.get(mw, 'o')
            label = mw.upper()

            # Plot 1: Median latency
            ax = axes[0][0]
            medians = [e['aggregate']['median_us'] for e in exps]
            ax.plot(nodes, medians, f'-{marker}', color=color, label=label, linewidth=2, markersize=8)
            ax.set_xlabel('Number of subscribers')
            ax.set_ylabel('Latency (us)')
            ax.set_title('Median End-to-End Latency')
            ax.legend()
            ax.grid(True, alpha=0.3)

            # Plot 2: P95 and P99 latency
            ax = axes[0][1]
            p95s = [e['aggregate']['p95_us'] for e in exps]
            p99s = [e['aggregate']['p99_us'] for e in exps]
            ax.plot(nodes, p95s, f'-{marker}', color=color, label=f'{label} P95', linewidth=2, markersize=8)
            ax.plot(nodes, p99s, f'--{marker}', color=color, label=f'{label} P99', linewidth=1.5, markersize=6, alpha=0.7)
            ax.set_xlabel('Number of subscribers')
            ax.set_ylabel('Latency (us)')
            ax.set_title('Tail Latency (P95 / P99)')
            ax.legend()
            ax.grid(True, alpha=0.3)

            # Plot 3: Discovery time
            ax = axes[1][0]
            disc_mean = [e['discovery']['mean_ms'] for e in exps]
            disc_min = [e['discovery']['min_ms'] for e in exps]
            disc_max = [e['discovery']['max_ms'] for e in exps]
            ax.plot(nodes, disc_mean, f'-{marker}', color=color, label=f'{label} mean', linewidth=2, markersize=8)
            ax.fill_between(nodes, disc_min, disc_max, color=color, alpha=0.15)
            ax.set_xlabel('Number of subscribers')
            ax.set_ylabel('Discovery time (ms)')
            ax.set_title('Discovery Time (mean + min/max range)')
            ax.legend()
            ax.grid(True, alpha=0.3)

            # Plot 4: CPU usage
            ax = axes[1][1]
            cpus = [e['docker_stats']['total_cpu_avg_pct'] if e['docker_stats'] else 0 for e in exps]
            ax.plot(nodes, cpus, f'-{marker}', color=color, label=label, linewidth=2, markersize=8)
            ax.set_xlabel('Number of subscribers')
            ax.set_ylabel('Total CPU usage (%)')
            ax.set_title('Aggregate CPU Usage (all containers)')
            ax.legend()
            ax.grid(True, alpha=0.3)

            # Plot 5: Delivery latency (middleware + transport)
            ax = axes[2][0]
            deliv = [e['aggregate']['delivery_median_us'] for e in exps]
            ax.plot(nodes, deliv, f'-{marker}', color=color, label=label, linewidth=2, markersize=8)
            ax.set_xlabel('Number of subscribers')
            ax.set_ylabel('Median delivery time (us)')
            ax.set_title('Delivery Latency: Middleware + Transport\n(time from pre-publish to subscriber callback)')
            ax.legend()
            ax.grid(True, alpha=0.3)

            # Plot 6: Publish overhead
            ax = axes[2][1]
            pub = [e['aggregate']['publish_overhead_median_us'] for e in exps]
            ax.plot(nodes, pub, f'-{marker}', color=color, label=label, linewidth=2, markersize=8)
            ax.set_xlabel('Number of subscribers')
            ax.set_ylabel('Median publish overhead (us)')
            ax.set_title('Publish Overhead: Application Side\n(timestamp + memcpy before publish call)')
            ax.legend()
            ax.grid(True, alpha=0.3)

        plt.tight_layout()
        plot_path = plots_dir / f"scaling_{profile}.png"
        plt.savefig(plot_path, dpi=150, bbox_inches='tight')
        plt.close()
        print(f"  Plot saved: {plot_path}")

    # Combined profile comparison
    for mw in set(exp['middleware'] for exp in experiments if exp):
        fig, ax = plt.subplots(1, 1, figsize=(10, 6))
        fig.suptitle(f'{mw.upper()}: Median Latency by Message Profile', fontsize=13, fontweight='bold')
        profile_colors = {
            'twist': '#FF9800', 'imu': '#2196F3',
            'laserscan': '#9C27B0', 'pointcloud': '#F44336',
        }
        colors = {'cyclonedds': '#2196F3', 'zenoh': '#4CAF50',
                'zenoh_peer': '#4CAF50', 'zenoh_router': '#FF5722'}
        markers = {'cyclonedds': 'o', 'zenoh': 's',
                'zenoh_peer': 's', 'zenoh_router': '^'}
        for profile in profiles:
            exps = sorted(by_mw_profile[(mw, profile)], key=lambda x: x['num_nodes'])
            if not exps:
                continue
            nodes = [e['num_nodes'] for e in exps]
            medians = [e['aggregate']['median_us'] for e in exps]
            color = profile_colors.get(profile, '#999')
            ax.plot(nodes, medians, '-o', color=color, label=profile, linewidth=2, markersize=8)
        ax.set_xlabel('Number of subscribers')
        ax.set_ylabel('Median latency (us)')
        ax.legend()
        ax.grid(True, alpha=0.3)
        plt.tight_layout()
        plot_path = plots_dir / f"profiles_{mw}.png"
        plt.savefig(plot_path, dpi=150, bbox_inches='tight')
        plt.close()
        print(f"  Plot saved: {plot_path}")


def save_summary_csv(experiments, output_dir):
    summary_path = output_dir / "summary.csv"
    with open(summary_path, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow([
            'middleware', 'profile', 'topology', 'num_nodes',
            'num_subscribers_actual', 'total_messages',
            'mean_us', 'median_us', 'stddev_us', 'min_us', 'max_us',
            'p90_us', 'p95_us', 'p99_us',
            'pub_overhead_median_us', 'pub_overhead_mean_us',
            'delivery_median_us', 'delivery_mean_us',
            'discovery_min_ms', 'discovery_max_ms', 'discovery_mean_ms',
            'total_cpu_pct', 'total_mem_mib'
        ])

        for exp in sorted(experiments, key=lambda x: (x['middleware'], x['profile'], x['num_nodes']) if x else ('', '', 0)):
            if not exp:
                continue
            a = exp['aggregate']
            d = exp['discovery']
            ds = exp['docker_stats']
            writer.writerow([
                exp['middleware'], exp['profile'], exp['topology'], exp['num_nodes'],
                exp['num_subscribers_actual'], exp['total_messages'],
                f"{a['mean_us']:.1f}", f"{a['median_us']:.1f}",
                f"{a['stddev_us']:.1f}", f"{a['min_us']:.1f}", f"{a['max_us']:.1f}",
                f"{a['p90_us']:.1f}", f"{a['p95_us']:.1f}", f"{a['p99_us']:.1f}",
                f"{a['publish_overhead_median_us']:.1f}", f"{a['publish_overhead_mean_us']:.1f}",
                f"{a['delivery_median_us']:.1f}", f"{a['delivery_mean_us']:.1f}",
                f"{d['min_ms']:.1f}", f"{d['max_ms']:.1f}", f"{d['mean_ms']:.1f}",
                f"{ds['total_cpu_avg_pct']:.1f}" if ds else "",
                f"{ds['total_mem_avg_mib']:.1f}" if ds else "",
            ])
    print(f"  Summary CSV saved: {summary_path}")


def main():
    parser = argparse.ArgumentParser(description="Analyze benchmark results")
    parser.add_argument("--results-dir", default="results",
                        help="Path to results directory")
    parser.add_argument("--no-plots", action="store_true",
                        help="Skip plot generation")
    args = parser.parse_args()

    results_dir = Path(args.results_dir)
    if not results_dir.exists():
        print(f"ERROR: Results directory not found: {results_dir}")
        return

    print(f"\n{'='*60}")
    print(f"  ANALYZING RESULTS: {results_dir}")
    print(f"{'='*60}")

    experiments = []
    for mw_dir in sorted(results_dir.iterdir()):
        if not mw_dir.is_dir():
            continue
        for exp_dir in sorted(mw_dir.iterdir()):
            if not exp_dir.is_dir():
                continue
            exp_info = parse_experiment_dir(exp_dir)
            if exp_info:
                print(f"  Found: {exp_info['middleware']}/{exp_dir.name}")
                result = analyze_experiment(exp_info)
                if result:
                    experiments.append(result)
                else:
                    print(f"    WARNING: No valid data in {exp_dir}")

    if not experiments:
        print("\n  No experiments found. Run experiments first.")
        return

    print(f"\n  Total experiments analyzed: {len(experiments)}")

    profiles = sorted(set(e['profile'] for e in experiments))
    for profile in profiles:
        print_scaling_table(experiments, profile)

    middlewares = set(e['middleware'] for e in experiments)
    if len(middlewares) > 1:
        for profile in profiles:
            print_comparison_table(experiments, profile)

    if not args.no_plots:
        print(f"\n  Generating plots...")
        generate_plots(experiments, results_dir)

    save_summary_csv(experiments, results_dir)

    print(f"\n{'='*60}")
    print(f"  ANALYSIS COMPLETE")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
