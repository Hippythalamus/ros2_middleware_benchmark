#pragma once

#include <chrono>
#include <cstdint>
#include <string>
#include <string_view>
#include <variant>

namespace benchmark {

// ---------------------------------------------------------------
// Message profiles tied to real robotics workloads
// ---------------------------------------------------------------
enum class MessageProfile {
    Twist,          // ~48 bytes   — velocity commands, 50-100 Hz
    Imu,            // ~300 bytes  — inertial measurement, 100-500 Hz
    LaserScan,      // ~10 KB      — 2D lidar, 10-40 Hz
    PointCloud2     // ~200 KB     — 3D lidar chunk, 10-20 Hz
};

struct ProfileConfig {
    MessageProfile profile;
    std::string_view name;
    std::size_t approx_bytes;
    double default_hz;
};

// Compile-time profile table
constexpr ProfileConfig kProfiles[] = {
    {MessageProfile::Twist,       "twist",        48,      50.0},
    {MessageProfile::Imu,         "imu",         300,     100.0},
    {MessageProfile::LaserScan,   "laserscan",  10240,     20.0},
    {MessageProfile::PointCloud2, "pointcloud", 204800,    10.0},
};

[[nodiscard]] constexpr const ProfileConfig& 
get_profile(MessageProfile p) noexcept {
    for (const auto& cfg : kProfiles) {
        if (cfg.profile == p) return cfg;
    }
    return kProfiles[0]; // fallback
}

// ---------------------------------------------------------------
// Experiment parameters (set via ROS2 params or env)
// ---------------------------------------------------------------
struct ExperimentConfig {
    // Which message profile to use
    MessageProfile profile = MessageProfile::Imu;

    // Publishing frequency in Hz
    double publish_rate_hz = 100.0;

    // How many messages to send per experiment run
    std::uint64_t num_messages = 5000;

    // Warmup messages (discarded from metrics)
    std::uint64_t warmup_messages = 500;

    // Mock computation delay in subscriber (microseconds)
    // Simulates processing time, same for both middleware
    std::uint64_t mock_processing_us = 100;

    // Node identity
    std::uint32_t node_id = 0;

    // Output CSV path
    std::string output_path = "/ws/results/";
};

// ---------------------------------------------------------------
// Metric record written per received message
// ---------------------------------------------------------------
struct LatencyRecord {
    std::uint64_t seq;                    // message sequence number

    // --- Raw timestamps ---
    std::int64_t  t1_ns;                  // before publish (publisher)
    std::int64_t  t2_ns;                  // before publish call (publisher)
    std::int64_t  receive_timestamp_ns;   // subscriber receive time (t3)

    // --- Derived metrics ---
    std::int64_t  publish_overhead_ns;    // t2 - t1
    std::int64_t  delivery_ns;            // t3 - t2
    std::int64_t  latency_ns;             // t3 - t1

    std::uint32_t publisher_id;
    std::uint32_t subscriber_id;
};

// ---------------------------------------------------------------
// Utility: high-resolution clock shorthand
// ---------------------------------------------------------------
inline std::int64_t now_ns() noexcept {
    return std::chrono::steady_clock::now()
        .time_since_epoch()
        .count();
}

} // namespace benchmark
