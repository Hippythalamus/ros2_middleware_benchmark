/// @file clock_check.cpp
/// @brief Clock synchronization verifier for Docker containers.
///
/// Publishes and subscribes to a timestamp topic to measure clock skew
/// between containers sharing the same kernel. Run before experiments
/// to validate that steady_clock is consistent.
///
/// Usage:
///   Container A: ros2 run benchmark_node clock_check --ros-args -p mode:=pub -p node_id:=0
///   Container B: ros2 run benchmark_node clock_check --ros-args -p mode:=sub -p node_id:=1

#include <chrono>
#include <cstdint>
#include <cstring>
#include <memory>
#include <string>
#include <vector>
#include <numeric>
#include <algorithm>
#include <cmath>

#include "rclcpp/rclcpp.hpp"
#include "std_msgs/msg/byte_multi_array.hpp"
#include "benchmark_node/config.hpp"

namespace benchmark {

class ClockCheckNode : public rclcpp::Node {
public:
    ClockCheckNode()
        : Node("clock_check")
    {
        declare_parameter("mode", "pub");
        declare_parameter("node_id", 0);
        declare_parameter("num_samples", 100);

        mode_ = get_parameter("mode").as_string();
        node_id_ = static_cast<std::uint32_t>(get_parameter("node_id").as_int());
        num_samples_ = static_cast<std::size_t>(get_parameter("num_samples").as_int());

        auto qos = rclcpp::QoS(rclcpp::KeepLast(10)).reliable();

        if (mode_ == "pub") {
            publisher_ = create_publisher<std_msgs::msg::ByteMultiArray>("clock_check", qos);
            timer_ = create_wall_timer(
                std::chrono::milliseconds(50),
                std::bind(&ClockCheckNode::publish_tick, this));
            RCLCPP_INFO(get_logger(), "Clock check PUBLISHER [id=%u]", node_id_);
        } else {
            deltas_.reserve(num_samples_);
            subscription_ = create_subscription<std_msgs::msg::ByteMultiArray>(
                "clock_check", qos,
                std::bind(&ClockCheckNode::on_tick, this, std::placeholders::_1));
            RCLCPP_INFO(get_logger(), "Clock check SUBSCRIBER [id=%u] waiting for %zu samples",
                node_id_, num_samples_);
        }
    }

private:
    void publish_tick() {
        // Wait for at least one subscriber before sending
        if (publisher_->get_subscription_count() == 0) {
            if (!waiting_logged_) {
                RCLCPP_INFO(get_logger(), "Publisher waiting for subscribers...");
                waiting_logged_ = true;
            }
            return;
        }

        if (waiting_logged_ && !started_logged_) {
            RCLCPP_INFO(get_logger(), "Subscriber found! Starting to publish.");
            started_logged_ = true;
        }

        auto msg = std_msgs::msg::ByteMultiArray();
        msg.data.resize(8);
        const auto ts = now_ns();
        std::memcpy(msg.data.data(), &ts, sizeof(ts));
        publisher_->publish(msg);
        ++count_;

        if (count_ % 25 == 0) {
            RCLCPP_INFO(get_logger(), "Published %zu / %zu ticks", count_, num_samples_ + 50);
        }

        if (count_ >= num_samples_ + 50) {
            RCLCPP_INFO(get_logger(), "Publisher done, sent %zu ticks", count_);
            rclcpp::shutdown();
        }
    }

    void on_tick(const std_msgs::msg::ByteMultiArray::SharedPtr msg) {
        const auto receive_ts = now_ns();

        if (msg->data.size() < 8) return;

        std::int64_t publish_ts = 0;
        std::memcpy(&publish_ts, msg->data.data(), sizeof(publish_ts));

        const auto delta = receive_ts - publish_ts;
        deltas_.push_back(delta);

        if (deltas_.size() >= num_samples_) {
            report();
            rclcpp::shutdown();
        }
    }

    void report() {
        if (deltas_.empty()) return;

        // Stats
        const auto n = static_cast<double>(deltas_.size());
        const auto sum = std::accumulate(deltas_.begin(), deltas_.end(), 0LL);
        const auto mean = static_cast<double>(sum) / n;
        const auto [min_it, max_it] = std::minmax_element(deltas_.begin(), deltas_.end());

        double variance = 0.0;
        for (const auto d : deltas_) {
            const auto diff = static_cast<double>(d) - mean;
            variance += diff * diff;
        }
        variance /= n;
        const auto stddev = std::sqrt(variance);

        RCLCPP_INFO(get_logger(),
            "\n=== CLOCK CHECK RESULTS (subscriber id=%u) ===\n"
            "  Samples:  %zu\n"
            "  Mean:     %.1f ns (%.3f us)\n"
            "  Stddev:   %.1f ns (%.3f us)\n"
            "  Min:      %ld ns\n"
            "  Max:      %ld ns\n"
            "  Range:    %ld ns\n"
            "==============================================\n"
            "  If mean < 1000 ns and stddev < 500 ns,\n"
            "  clocks are well-synchronized for our benchmark.\n"
            "==============================================",
            node_id_,
            deltas_.size(),
            mean, mean / 1000.0,
            stddev, stddev / 1000.0,
            *min_it,
            *max_it,
            *max_it - *min_it);
    }

    // --- Members ---
    std::string mode_;
    std::uint32_t node_id_ = 0;
    std::size_t num_samples_ = 100;
    std::size_t count_ = 0;
    bool waiting_logged_ = false;
    bool started_logged_ = false;

    rclcpp::Publisher<std_msgs::msg::ByteMultiArray>::SharedPtr publisher_;
    rclcpp::Subscription<std_msgs::msg::ByteMultiArray>::SharedPtr subscription_;
    rclcpp::TimerBase::SharedPtr timer_;

    std::vector<std::int64_t> deltas_;
};

} // namespace benchmark

int main(int argc, char* argv[]) {
    rclcpp::init(argc, argv);
    rclcpp::spin(std::make_shared<benchmark::ClockCheckNode>());
    rclcpp::shutdown();
    return 0;
}
