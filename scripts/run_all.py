#!/usr/bin/env python3
"""
Run the full benchmark suite automatically.

Iterates over all combinations of middleware, node counts, and profiles.
Results are saved to results/<middleware>/<topology>_<profile>_<N>nodes/

Usage:
    python3 scripts/run_all.py
    python3 scripts/run_all.py --quick          # reduced set for testing
    python3 scripts/run_all.py --rmw cyclone    # only CycloneDDS
    python3 scripts/run_all.py --rmw zenoh      # only Zenoh
"""

import argparse
import subprocess
import sys
import time
from pathlib import Path


# Full experiment matrix
MIDDLEWARE = {
    "cyclone": "rmw_cyclonedds_cpp",
    "zenoh": "rmw_zenoh_cpp",
}

NODE_COUNTS = [2, 5, 10, 15, 20, 30, 40]
NODE_COUNTS_QUICK = [2, 5, 10, 20, 30]

PROFILES = {
    "twist":      {"rate_hz": 50.0},
    "imu":        {"rate_hz": 100.0},
    "laserscan":  {"rate_hz": 20.0},
    "pointcloud": {"rate_hz": 10.0},
}
PROFILES_QUICK = {
    "imu": {"rate_hz": 100.0},
}

TOPOLOGIES = ["fanout"]  # fanin and mesh added later

MESSAGES = 5000
WARMUP = 500
MOCK_US = 100


def run_single(rmw, profile, rate_hz, subscribers, topology, messages, warmup, mock_us):
    """Run a single experiment via run_experiment.py."""
    cmd = [
        sys.executable, "scripts/run_experiment.py",
        "--rmw", rmw,
        "--profile", profile,
        "--subscribers", str(subscribers),
        "--messages", str(messages),
        "--warmup", str(warmup),
        "--mock-us", str(mock_us),
        "--rate-hz", str(rate_hz),
        "--topology", topology,
    ]

    print(f"\n{'#'*60}")
    print(f"  RUNNING: {rmw} | {profile} | {subscribers} subs | {topology}")
    print(f"{'#'*60}")

    result = subprocess.run(cmd)
    return result.returncode == 0


def main():
    parser = argparse.ArgumentParser(description="Run full benchmark suite")
    parser.add_argument("--quick", action="store_true",
                        help="Reduced set: IMU only, fewer node counts")
    parser.add_argument("--rmw", default="all",
                        choices=["all", "cyclone", "zenoh"],
                        help="Which middleware to test")
    parser.add_argument("--messages", type=int, default=MESSAGES,
                        help="Messages per experiment")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print experiments without running")
    args = parser.parse_args()

    # Build experiment matrix
    if args.rmw == "all":
        middlewares = MIDDLEWARE
    else:
        middlewares = {args.rmw: MIDDLEWARE[args.rmw]}

    node_counts = NODE_COUNTS_QUICK if args.quick else NODE_COUNTS
    profiles = PROFILES_QUICK if args.quick else PROFILES

    # Calculate total experiments
    experiments = []
    for rmw_name, rmw_impl in middlewares.items():
        for profile, pcfg in profiles.items():
            for n in node_counts:
                for topo in TOPOLOGIES:
                    experiments.append({
                        "rmw_name": rmw_name,
                        "rmw_impl": rmw_impl,
                        "profile": profile,
                        "rate_hz": pcfg["rate_hz"],
                        "subscribers": n,
                        "topology": topo,
                    })

    total = len(experiments)
    est_minutes = total * 2  # rough estimate: ~2 min per experiment
    print(f"\n{'='*60}")
    print(f"  BENCHMARK SUITE")
    print(f"  Total experiments: {total}")
    print(f"  Estimated time:    ~{est_minutes} minutes ({est_minutes/60:.1f} hours)")
    print(f"  Messages per run:  {args.messages}")
    print(f"  Mode:              {'QUICK' if args.quick else 'FULL'}")
    print(f"{'='*60}")

    if args.dry_run:
        print("\n  DRY RUN - experiments that would be executed:\n")
        for i, exp in enumerate(experiments, 1):
            print(f"  {i:>3}. {exp['rmw_name']:>8} | {exp['profile']:>10} | "
                  f"{exp['subscribers']:>3} subs | {exp['topology']}")
        print(f"\n  Total: {total} experiments")
        return

    # Run all experiments
    start_time = time.time()
    results = []

    for i, exp in enumerate(experiments, 1):
        print(f"\n{'='*60}")
        print(f"  [{i}/{total}] Starting...")
        print(f"{'='*60}")

        success = run_single(
            rmw=exp["rmw_impl"],
            profile=exp["profile"],
            rate_hz=exp["rate_hz"],
            subscribers=exp["subscribers"],
            topology=exp["topology"],
            messages=args.messages,
            warmup=WARMUP,
            mock_us=MOCK_US,
        )

        results.append({**exp, "success": success})

        elapsed = time.time() - start_time
        avg_per_exp = elapsed / i
        remaining = avg_per_exp * (total - i)
        print(f"  [{i}/{total}] {'OK' if success else 'FAILED'} | "
              f"Elapsed: {elapsed/60:.1f}min | ETA: {remaining/60:.1f}min")

        # Brief pause between experiments for cleanup
        time.sleep(5)

    # Summary
    total_time = time.time() - start_time
    succeeded = sum(1 for r in results if r['success'])
    failed = [r for r in results if not r['success']]

    print(f"\n{'='*60}")
    print(f"  SUITE COMPLETE")
    print(f"  Total time:  {total_time/60:.1f} minutes")
    print(f"  Succeeded:   {succeeded}/{total}")
    if failed:
        print(f"  Failed:")
        for r in failed:
            print(f"    - {r['rmw_name']} | {r['profile']} | {r['subscribers']} subs")
    print(f"{'='*60}")

    # Run analyzer
    print(f"\n  Running analyzer...")
    subprocess.run([sys.executable, "scripts/analyze.py"])


if __name__ == "__main__":
    main()
