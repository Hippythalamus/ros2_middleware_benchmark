/// @file publisher_node.cpp
/// @brief Benchmark publisher: sends timestamped messages at configurable rate.
///
/// The timestamp is embedded in the message header (or first bytes of data)
/// so the subscriber can compute one-way latency. We use std_msgs::msg::Header
/// stamp field in all messages to carry the publisher's steady_clock reading.
///
/// Usage:
///   ros2 run benchmark_node publisher
///     --ros-args -p profile:=imu -p rate_hz:=100 -p node_id:=0 -p num_messages:=5000

#include <chrono>
#include <cstdint>
#include <functional>
#include <memory>
#include <string>
#include <vector>

#include "rclcpp/rclcpp.hpp"
#include "std_msgs/msg/byte_multi_array.hpp"
#include "benchmark_node/config.hpp"

namespace benchmark {

class PublisherNode : public rclcpp::Node {
public:
    PublisherNode()
        : Node("bench_publisher")
    {
        // --- Declare parameters ---
        declare_parameter("profile", "imu");
        declare_parameter("rate_hz", 100.0);
        declare_parameter("node_id", 0);
        declare_parameter("num_messages", 5000);
        declare_parameter("warmup_messages", 500);
        declare_parameter("topic", "bench_topic");

        // --- Read parameters ---
        const auto profile_str = get_parameter("profile").as_string();
        const auto rate_hz = get_parameter("rate_hz").as_double();
        node_id_ = static_cast<std::uint32_t>(get_parameter("node_id").as_int());
        num_messages_ = static_cast<std::uint64_t>(get_parameter("num_messages").as_int());
        warmup_ = static_cast<std::uint64_t>(get_parameter("warmup_messages").as_int());
        const auto topic = get_parameter("topic").as_string();

        // Resolve profile
        profile_ = resolve_profile(profile_str);
        const auto& pcfg = get_profile(profile_);
        payload_size_ = pcfg.approx_bytes;

        RCLCPP_INFO(get_logger(),
            "Publisher [id=%u] profile=%s payload=%zu bytes rate=%.1f Hz msgs=%lu topic=%s",
            node_id_, std::string(pcfg.name).c_str(), payload_size_,
            rate_hz, num_messages_, topic.c_str());

        // --- Create publisher ---
        // Use RELIABLE QoS for benchmark consistency, keep_last(10)
        auto qos = rclcpp::QoS(rclcpp::KeepLast(10)).reliable();
        publisher_ = create_publisher<std_msgs::msg::ByteMultiArray>(topic, qos);

        // --- Prepare payload template ---
        // Layout: [8 bytes timestamp_ns] [4 bytes seq] [4 bytes node_id] [padding...]
        constexpr std::size_t kHeaderSize = 16; // 8 + 4 + 4
        const auto total = std::max(payload_size_, kHeaderSize);
        payload_template_.resize(total, 0);

        // --- Timer ---
        const auto period = std::chrono::duration<double>(1.0 / rate_hz);
        timer_ = create_wall_timer(
            std::chrono::duration_cast<std::chrono::nanoseconds>(period),
            std::bind(&PublisherNode::on_timer, this));
    }

private:
    void on_timer() {
        // Wait for at least one subscriber before sending
        if (publisher_->get_subscription_count() == 0) {
            if (!waiting_logged_) {
                RCLCPP_INFO(get_logger(), "Publisher [id=%u] waiting for subscribers...", node_id_);
                waiting_logged_ = true;
            }
            return;
        }

        if (waiting_logged_ && !started_logged_) {
            RCLCPP_INFO(get_logger(), "Publisher [id=%u] subscriber found, starting.", node_id_);
            started_logged_ = true;
        }

        if (seq_ >= num_messages_ + warmup_) {
            RCLCPP_INFO(get_logger(), "Publisher [id=%u] finished: %lu messages sent",
                node_id_, seq_);
            timer_->cancel();
            // Give subscribers time to receive last messages
            rclcpp::shutdown();
            return;
        }

        auto msg = std_msgs::msg::ByteMultiArray();
        msg.data = payload_template_;

        // Stamp current time (nanoseconds since epoch of steady_clock)
        const auto ts = now_ns();

        // Embed header: [timestamp_ns(8)][seq(4)][node_id(4)]
        std::memcpy(msg.data.data(),     &ts,       sizeof(ts));
        std::memcpy(msg.data.data() + 8, &seq_,     sizeof(seq_));
        std::memcpy(msg.data.data() + 12, &node_id_, sizeof(node_id_));

        publisher_->publish(msg);
        ++seq_;
    }

    [[nodiscard]] static MessageProfile resolve_profile(const std::string& name) {
        if (name == "twist")      return MessageProfile::Twist;
        if (name == "imu")        return MessageProfile::Imu;
        if (name == "laserscan")  return MessageProfile::LaserScan;
        if (name == "pointcloud") return MessageProfile::PointCloud2;
        return MessageProfile::Imu; // default
    }

    // --- Members ---
    rclcpp::Publisher<std_msgs::msg::ByteMultiArray>::SharedPtr publisher_;
    rclcpp::TimerBase::SharedPtr timer_;
    std::vector<std::uint8_t> payload_template_;

    MessageProfile profile_ = MessageProfile::Imu;
    std::size_t payload_size_ = 300;
    std::uint32_t node_id_ = 0;
    std::uint64_t num_messages_ = 5000;
    std::uint64_t warmup_ = 500;
    std::uint64_t seq_ = 0;
    bool waiting_logged_ = false;
    bool started_logged_ = false;
};

} // namespace benchmark

int main(int argc, char* argv[]) {
    rclcpp::init(argc, argv);
    rclcpp::spin(std::make_shared<benchmark::PublisherNode>());
    rclcpp::shutdown();
    return 0;
}
