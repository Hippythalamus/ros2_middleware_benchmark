# ROS2 Middleware Scalability Benchmark

### CycloneDDS vs Zenoh: At What Scale Does Your Middleware Break?

> A systematic, reproducible benchmark measuring how CycloneDDS and Zenoh behave as the number of ROS2 nodes scales from 2 to 40, using message profiles tied to real robotics workloads.

---

## Motivation

ROS2 middleware performance is well-studied for two-host setups and varying network conditions ([Zhang et al. 2023](https://arxiv.org/abs/2309.07496), [Springer 2024](https://link.springer.com/article/10.1007/s10846-024-02211-2)). Discovery overhead reduction with Zenoh has been reported at 97-99% ([ZettaScale blog](https://zenoh.io/blog/2021-03-23-discovery/)).

However, no published work systematically answers a practical engineering question:

**At what node count does DDS discovery overhead start degrading latency, and how does Zenoh compare at the same scale?**

This benchmark fills that gap. All experiments use default middleware configurations (no tuning), real-world message sizes, and a fixed mock computation delay to isolate transport overhead from application logic.

---

## Experiment Design

### Independent Variable

Number of ROS2 nodes: **2, 5, 10, 15, 20, 30, 40**

### Measured Metrics

| Metric | Method |
|---|---|
| **End-to-end latency** | `steady_clock` timestamp embedded by publisher, delta computed on receive |
| **Discovery time** | Interval from node startup to first message received |
| **Throughput** | Messages per second actually delivered to subscribers |
| **CPU usage** | Per-container, collected via `docker stats` |
| **Memory (RSS)** | Per-container, collected via `docker stats` |
| **Jitter** | Standard deviation of latency across all non-warmup messages |

### Message Profiles

Message sizes are tied to real ROS2 robotics workloads, not arbitrary byte counts:

| Profile | Approx. Size | Real-World Equivalent | Default Frequency |
|---|---|---|---|
| `twist` | 48 B | `geometry_msgs/Twist` velocity commands | 50 Hz |
| `imu` | 300 B | `sensor_msgs/Imu` inertial measurement unit | 100 Hz |
| `laserscan` | 10 KB | `sensor_msgs/LaserScan` 2D lidar scan | 20 Hz |
| `pointcloud` | 200 KB | `sensor_msgs/PointCloud2` 3D lidar chunk | 10 Hz |

### Communication Topologies

| Topology | Description | Real-World Scenario |
|---|---|---|
| **Fan-out** | 1 publisher, N subscribers | Sensor broadcast to multiple consumers |
| **Fan-in** | N publishers, 1 subscriber | Sensor fusion from multiple sources |
| **Mesh** | N-to-N | Multi-agent coordination |

### Middleware Under Test

| Middleware | RMW Implementation | Configuration |
|---|---|---|
| **CycloneDDS** | `rmw_cyclonedds_cpp` | Default (no tuning) |
| **Zenoh** | `rmw_zenoh_cpp` | Default (no tuning) |

Same application code for both. Only the `RMW_IMPLEMENTATION` environment variable changes between runs.

### Mock Computation

Each subscriber applies a fixed `sleep` (default: 100 us) after receiving a message to simulate processing time. This value is identical for both middleware, isolating transport overhead from application logic.

### Warmup

First 500 messages per run are tagged as warmup and excluded from analysis. This ensures DDS discovery settling and cache warming do not skew results.

---

## Architecture

```
+-----------------------------------------------------+
|                    Host Machine                      |
|                Ubuntu, 4 cores, 16 GB                |
|                                                      |
|  +----------+  +----------+       +----------+       |
|  |Publisher  |  |Subscriber|  ...  |Subscriber|       |
|  |Container |  |Container |       |Container |       |
|  |  node_0  |  |  node_1  |       |  node_N  |       |
|  +----+-----+  +----+-----+       +----+-----+       |
|       |              |                  |             |
|       +--------------+------------------+             |
|                Docker bridge network                  |
|           RMW: CycloneDDS or Zenoh                    |
|                                                       |
|  +----------------------------------------------+     |
|  | Orchestrator (Python)                         |     |
|  |  - Launches containers                        |     |
|  |  - Collects docker stats (CPU/RAM)            |     |
|  |  - Aggregates CSV results                     |     |
|  +----------------------------------------------+     |
|                                                       |
|  results/                                             |
|  +-- cyclonedds/                                      |
|  |   +-- fanout_imu_10nodes/                          |
|  |   |   +-- sub_1.csv                                |
|  |   |   +-- sub_2.csv                                |
|  |   |   +-- docker_stats.csv                         |
|  |   +-- ...                                          |
|  +-- zenoh/                                           |
|      +-- ...                                          |
+-------------------------------------------------------+
```

---

## Project Structure

```
ros2_middleware_benchmark/
|-- docker/
|   |-- Dockerfile              # ROS2 Humble + CycloneDDS + Zenoh RMW
|   |-- docker-compose.yml      # Container orchestration
|   +-- entrypoint.sh           # Sources ROS2 + workspace
|-- src/                        # ROS2 package (ament_cmake)
|   |-- CMakeLists.txt
|   |-- package.xml
|   |-- include/
|   |   +-- benchmark_node/
|   |       +-- config.hpp      # Message profiles, experiment config, metric types
|   +-- src/
|       |-- publisher_node.cpp  # Configurable publisher with embedded timestamps
|       |-- subscriber_node.cpp # Latency measurement, mock processing, CSV output
|       +-- clock_check.cpp     # Clock sync verification between containers
|-- scripts/
|   |-- run_experiment.py       # Single experiment runner
|   |-- run_all.py              # Full experiment suite
|   +-- analyze.py              # Aggregation, statistics, plot generation
|-- results/                    # Raw CSV data + generated plots
+-- README.md
```

---

## Quick Start

### Prerequisites

- Docker and Docker Compose
- Python 3.8+ (for orchestration and analysis)
- ~10 GB disk space for Docker images

### Build

```bash
docker build -f docker/Dockerfile -t ros2_benchmark:humble --no-cache .
```

### Verify Clock Synchronization

Before running experiments, verify that `steady_clock` is consistent across containers (expected on single-host Docker with shared kernel):

```bash
terminal 1
docker compose run --rm subscriber
terminal 2 
docker compose run --rm publisher
```

Expected output: mean delta < 1000 ns, stddev < 500 ns.

### Run a Single Experiment

```bash
# 10 subscribers, IMU profile, CycloneDDS
RMW=rmw_cyclonedds_cpp SUBS=10 PROFILE=imu python3 scripts/run_experiment.py
```

### Run Full Experiment Suite

```bash
python3 scripts/run_all.py
```

This iterates over all combinations of:
- Middleware: CycloneDDS, Zenoh
- Node counts: 2, 5, 10, 15, 20, 30, 40
- Profiles: twist, imu, laserscan, pointcloud
- Topologies: fan-out, fan-in, mesh

### Analyze Results

```bash
python3 scripts/analyze.py
```

Generates plots and summary statistics in `results/`.

---

## Implementation Details

### Timestamp Mechanism

Each message carries a binary header:

| Offset | Size | Field | Description |
|---|---|---|---|
| 0 | 8 bytes | `timestamp_ns` | Publisher's `steady_clock` reading (nanoseconds) |
| 8 | 4 bytes | `seq` | Sequence number |
| 12 | 4 bytes | `node_id` | Publisher identity |
| 16+ | variable | padding | Zero-filled to match profile size |

Subscriber computes `latency_ns = receive_timestamp - publish_timestamp` immediately on callback entry, before mock processing.

### QoS Configuration

All experiments use `RELIABLE` QoS with `KeepLast(10)` for both publisher and subscriber. This ensures no silent message drops that would skew throughput measurements.

### C++17 Features Used

- `std::string_view` for zero-copy profile name handling
- `std::variant` for topology configuration
- `constexpr` compile-time profile table
- `[[nodiscard]]` for API safety
- Structured bindings where applicable
- `std::optional` for nullable parameters

---

## Known Limitations

| # | Limitation | Impact | Mitigation |
|---|---|---|---|
| 1 | **Single host** | No real network effects (multicast flooding, packet loss, Wi-Fi jitter) | We measure middleware software overhead and scaling, not network. Complements [Zhang et al. 2023](https://arxiv.org/abs/2309.07496) which covers network. |
| 2 | **Resource contention** | 40 containers on 4 cores share CPU. Degradation appears earlier than on distributed hardware. | CPU load documented per experiment. Results state hardware specs explicitly. |
| 3 | **Docker overhead** | Container networking adds latency vs native processes. | Control measurement: 2 nodes native vs Docker. Delta documented. |
| 4 | **Default configs only** | DDS performance is tuning-dependent. Results may not reflect optimized setups. | Intentional: default settings represent typical developer experience. Tuned comparison planned for Publication 2. |
| 5 | **Fixed mock computation** | Real workloads vary. | Fixed delay isolates transport overhead, which is the subject of this study. |

---

## Planned Work

- [ ] **Publication 1** (current): Default middleware configurations, full scaling analysis
- [ ] **Publication 2**: Tuned CycloneDDS configuration, showing how optimization shifts the degradation threshold
- [ ] Multi-host experiments (2+ machines) to validate single-host findings
- [ ] Integration with `ros2_tracing` for deeper profiling

---

## Related Work

- Zhang, J. et al. (2023). *Comparison of Middlewares in Edge-to-Edge and Edge-to-Cloud Communication for Distributed ROS2 Systems.* [arXiv:2309.07496](https://arxiv.org/abs/2309.07496)
- ZettaScale (2021). *Minimizing Discovery Overhead in ROS2.* [zenoh.io/blog](https://zenoh.io/blog/2021-03-23-discovery/)
- Springer (2024). *Performance Comparison of ROS2 Middlewares for Multi-robot Mesh Networks in Planetary Exploration.* [DOI](https://link.springer.com/article/10.1007/s10846-024-02211-2)
- Open Robotics (2021). *ROS Middleware Evaluation Report.* [TSC-RMW-Reports](https://osrf.github.io/TSC-RMW-Reports/humble/)

---

## License

MIT

## Author

**Evgeniia Slepynina** -- Senior C++ / Robotics Engineer  
Specializing in real-time systems, autonomous robot control, and system architecture.

- [LinkedIn](https://www.linkedin.com/in/evgeniia-slepynina-a3802a249)
- slepynina.eu@gmail.com

---

*If you find this benchmark useful, consider giving it a star and sharing with the ROS2 community.*
