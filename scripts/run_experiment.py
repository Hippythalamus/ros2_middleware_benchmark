#!/usr/bin/env python3
"""
Automated experiment orchestrator for ROS2 middleware benchmark.

Launches N subscriber containers, waits for them to initialize,
then launches the publisher. Waits for ALL containers to finish naturally.

Usage:
    python3 scripts/run_experiment.py \
        --rmw rmw_cyclonedds_cpp \
        --profile imu \
        --subscribers 10 \
        --topology fanout \
        --messages 5000
"""

import argparse
import subprocess
import time
import os
import threading
from pathlib import Path


DOCKER_IMAGE = "ros2_benchmark:humble"
NETWORK_NAME = "ros_bench"

# How long to wait for subscriber containers to initialize (seconds)
SUBSCRIBER_INIT_WAIT = 3
# How long between launching each subscriber (seconds)
SUBSCRIBER_STAGGER = 0.5
# Max time to wait for all containers to finish (seconds)
MAX_EXPERIMENT_TIME = 600  # 10 minutes


def ensure_network():
    """Create Docker network if it doesn't exist."""
    result = subprocess.run(
        ["docker", "network", "ls", "--format", "{{.Name}}"],
        capture_output=True, text=True
    )
    if NETWORK_NAME not in result.stdout.strip().split("\n"):
        print(f"[orch] Creating Docker network: {NETWORK_NAME}")
        subprocess.run(["docker", "network", "create", NETWORK_NAME], check=True)


def cleanup_containers(prefix="bench_"):
    """Stop and remove any leftover benchmark containers."""
    result = subprocess.run(
        ["docker", "ps", "-a", "--format", "{{.Names}}"],
        capture_output=True, text=True
    )
    for name in result.stdout.strip().split("\n"):
        if name and name.startswith(prefix):
            print(f"[orch] Removing leftover container: {name}")
            subprocess.run(["docker", "rm", "-f", name], capture_output=True)


def wait_for_container(name, proc, results_dict):
    """Wait for a container to finish and capture output."""
    try:
        proc.wait()
        output = proc.stdout.read().decode() if proc.stdout else ""
        results_dict[name] = {
            'returncode': proc.returncode,
            'output': output
        }
    except Exception as e:
        results_dict[name] = {
            'returncode': -1,
            'output': str(e)
        }


def run_experiment(args):
    rmw = args.rmw
    profile = args.profile
    num_subs = args.subscribers
    num_messages = args.messages
    warmup = args.warmup
    mock_us = args.mock_us
    rate_hz = args.rate_hz
    topology = args.topology

    # Result directory
    rmw_short = "cyclonedds" if "cyclone" in rmw else "zenoh"
    experiment_name = f"{topology}_{profile}_{num_subs}nodes"
    result_dir = Path("results") / rmw_short / experiment_name
    result_dir.mkdir(parents=True, exist_ok=True)

    # Clean old results
    for old_csv in result_dir.glob("sub_*.csv"):
        old_csv.unlink()

    print(f"\n{'='*60}")
    print(f"  EXPERIMENT: {experiment_name}")
    print(f"  RMW:        {rmw}")
    print(f"  Profile:    {profile}")
    print(f"  Subscribers: {num_subs}")
    print(f"  Messages:   {num_messages} (+{warmup} warmup)")
    print(f"  Mock delay: {mock_us} us")
    print(f"  Rate:       {rate_hz} Hz")
    print(f"  Output:     {result_dir}")
    print(f"{'='*60}\n")

    ensure_network()
    cleanup_containers()

    container_names = []
    wait_threads = []
    container_results = {}

    try:
        # --- Launch subscribers ---
        print(f"[orch] Launching {num_subs} subscriber(s)...")
        for i in range(num_subs):
            sub_id = i + 1
            name = f"bench_sub_{sub_id}"
            container_names.append(name)

            cmd = [
                "docker", "run", "--rm",
                "--network", NETWORK_NAME,
                "--name", name,
                "-e", f"RMW_IMPLEMENTATION={rmw}",
                "-v", f"{os.path.abspath(result_dir)}:/ws/results",
                DOCKER_IMAGE,
                "ros2", "run", "benchmark_node", "subscriber",
                "--ros-args",
                "-p", f"node_id:={sub_id}",
                "-p", f"mock_processing_us:={mock_us}",
                "-p", "output_path:=/ws/results/",
                "-p", f"warmup_messages:={warmup}",
                "-p", f"expected_messages:={num_messages}",
                "-p", "topic:=bench_topic",
            ]

            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

            # Thread to wait for this container
            t = threading.Thread(target=wait_for_container, args=(name, proc, container_results))
            t.start()
            wait_threads.append(t)

            print(f"  [+] Subscriber {sub_id} started")
            time.sleep(SUBSCRIBER_STAGGER)

        # Wait for subscribers to initialize
        print(f"[orch] Waiting {SUBSCRIBER_INIT_WAIT}s for subscribers to initialize...")
        time.sleep(SUBSCRIBER_INIT_WAIT)

        # --- Start docker stats collection ---
        stats_file = result_dir / "docker_stats.csv"
        stats_proc = start_stats_collection(container_names, stats_file)

        # --- Launch publisher ---
        pub_name = "bench_pub_0"
        container_names.append(pub_name)

        pub_cmd = [
            "docker", "run", "--rm",
            "--network", NETWORK_NAME,
            "--name", pub_name,
            "-e", f"RMW_IMPLEMENTATION={rmw}",
            "-v", f"{os.path.abspath(result_dir)}:/ws/results",
            DOCKER_IMAGE,
            "ros2", "run", "benchmark_node", "publisher",
            "--ros-args",
            "-p", f"profile:={profile}",
            "-p", f"rate_hz:={rate_hz}",
            "-p", "node_id:=0",
            "-p", f"num_messages:={num_messages}",
            "-p", f"warmup_messages:={warmup}",
            "-p", "topic:=bench_topic",
        ]

        pub_proc = subprocess.Popen(pub_cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        pub_thread = threading.Thread(
            target=wait_for_container,
            args=(pub_name, pub_proc, container_results)
        )
        pub_thread.start()
        wait_threads.append(pub_thread)
        print(f"  [+] Publisher started")

        # --- Wait for ALL containers to finish ---
        print(f"\n[orch] Waiting for all containers to finish (max {MAX_EXPERIMENT_TIME}s)...")
        start_time = time.time()

        for t in wait_threads:
            remaining = MAX_EXPERIMENT_TIME - (time.time() - start_time)
            if remaining <= 0:
                print("[orch] TIMEOUT reached!")
                break
            t.join(timeout=remaining)

        elapsed = time.time() - start_time
        print(f"[orch] All containers finished in {elapsed:.1f}s")

        # Stop stats collection
        if stats_proc:
            stats_proc.terminate()

        # Print container outputs
        for name in sorted(container_results.keys()):
            info = container_results[name]
            output_lines = info['output'].strip().split('\n')
            # Show last few lines of output
            relevant = [l for l in output_lines if '[INFO]' in l or '[WARN]' in l or '[ERROR]' in l]
            if relevant:
                print(f"\n  {name}:")
                for line in relevant[-3:]:
                    print(f"    {line}")

    finally:
        # Force cleanup only for containers that didn't exit
        print(f"\n[orch] Final cleanup...")
        for name in container_names:
            subprocess.run(["docker", "rm", "-f", name],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # --- Check results ---
    csv_files = sorted(result_dir.glob("sub_*.csv"))
    print(f"\n{'='*60}")
    print(f"  EXPERIMENT COMPLETE: {experiment_name}")
    print(f"  Time elapsed: {elapsed:.1f}s")
    print(f"  CSV files generated: {len(csv_files)} / {num_subs} expected")

    if len(csv_files) < num_subs:
        missing = set(range(1, num_subs + 1)) - {
            int(f.stem.split('_')[1]) for f in csv_files
        }
        print(f"  MISSING subscribers: {sorted(missing)}")

    for f in csv_files:
        lines = sum(1 for _ in open(f)) - 1
        print(f"    {f.name}: {lines} records")
    print(f"  Results in: {result_dir}")
    print(f"{'='*60}\n")

    return len(csv_files) == num_subs


def start_stats_collection(container_names, output_file):
    """Collect docker stats in background, write to CSV."""
    names_filter = "|".join(container_names)
    cmd = f"""
    echo "timestamp,container,cpu_percent,mem_usage_mb" > {output_file}
    while true; do
        docker stats --no-stream --format '{{{{.Name}}}},{{{{.CPUPerc}}}},{{{{.MemUsage}}}}' | \
        grep -E '{names_filter}' | \
        while IFS= read -r line; do
            echo "$(date +%s),$line" >> {output_file}
        done
        sleep 2
    done
    """
    proc = subprocess.Popen(
        ["bash", "-c", cmd],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )
    return proc


def main():
    parser = argparse.ArgumentParser(description="ROS2 Middleware Benchmark Orchestrator")
    parser.add_argument("--rmw", default="rmw_cyclonedds_cpp",
                        choices=["rmw_cyclonedds_cpp", "rmw_zenoh_cpp"],
                        help="RMW implementation to test")
    parser.add_argument("--profile", default="imu",
                        choices=["twist", "imu", "laserscan", "pointcloud"],
                        help="Message profile")
    parser.add_argument("--subscribers", type=int, default=5,
                        help="Number of subscriber nodes")
    parser.add_argument("--messages", type=int, default=5000,
                        help="Number of data messages (excluding warmup)")
    parser.add_argument("--warmup", type=int, default=500,
                        help="Number of warmup messages")
    parser.add_argument("--mock-us", type=int, default=100,
                        help="Mock processing delay in microseconds")
    parser.add_argument("--rate-hz", type=float, default=100.0,
                        help="Publishing rate in Hz")
    parser.add_argument("--topology", default="fanout",
                        choices=["fanout", "fanin", "mesh"],
                        help="Communication topology")
    args = parser.parse_args()

    run_experiment(args)


if __name__ == "__main__":
    main()
