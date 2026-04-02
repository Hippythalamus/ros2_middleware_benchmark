/// @file subscriber_node.cpp
/// @brief Benchmark subscriber: receives timestamped messages, measures latency,
///        applies mock computation delay, writes results to CSV.
///
/// Usage:
///   ros2 run benchmark_node subscriber
///     --ros-args -p node_id:=1 -p mock_processing_us:=100 -p output_path:=/ws/results/

#include <chrono>
#include <cstdint>
#include <cstring>
#include <fstream>
#include <memory>
#include <string>
#include <thread>
#include <vector>

#include "rclcpp/rclcpp.hpp"
#include "std_msgs/msg/byte_multi_array.hpp"
#include "benchmark_node/config.hpp"

namespace benchmark {

class SubscriberNode : public rclcpp::Node {
public:
    SubscriberNode()
        : Node("bench_subscriber")
    {
        // --- Declare parameters ---
        declare_parameter("node_id", 0);
        declare_parameter("mock_processing_us", 100);
        declare_parameter("output_path", "/ws/results/");
        declare_parameter("warmup_messages", 500);
        declare_parameter("expected_messages", 5000);
        declare_parameter("topic", "bench_topic");

        // --- Read parameters ---
        node_id_ = static_cast<std::uint32_t>(get_parameter("node_id").as_int());
        mock_delay_us_ = static_cast<std::uint64_t>(get_parameter("mock_processing_us").as_int());
        output_path_ = get_parameter("output_path").as_string();
        warmup_ = static_cast<std::uint64_t>(get_parameter("warmup_messages").as_int());
        expected_ = static_cast<std::uint64_t>(get_parameter("expected_messages").as_int());
        const auto topic = get_parameter("topic").as_string();

        RCLCPP_INFO(get_logger(),
            "Subscriber [id=%u] mock_delay=%lu us warmup=%lu expected=%lu topic=%s",
            node_id_, mock_delay_us_, warmup_, expected_, topic.c_str());

        // Pre-allocate records to avoid allocation during measurement
        records_.reserve(expected_ + warmup_);

        // --- Create subscription ---
        auto qos = rclcpp::QoS(rclcpp::KeepLast(10)).reliable();
        subscription_ = create_subscription<std_msgs::msg::ByteMultiArray>(
            topic, qos,
            std::bind(&SubscriberNode::on_message, this, std::placeholders::_1));

        // Discovery timestamp
        discovery_start_ns_ = now_ns();
    }

    ~SubscriberNode() override {
        write_csv();
    }

private:
    void on_message(const std_msgs::msg::ByteMultiArray::SharedPtr msg) {
        const auto receive_ts = now_ns();

        // Record discovery time on first message
        if (!first_message_received_) {
            first_message_received_ = true;
            discovery_time_ns_ = receive_ts - discovery_start_ns_;
            RCLCPP_INFO(get_logger(),
                "Subscriber [id=%u] first message received, discovery_time=%.3f ms",
                node_id_, static_cast<double>(discovery_time_ns_) / 1e6);
        }

        // Decode header: [timestamp_ns(8)][seq(4)][publisher_id(4)]
        if (msg->data.size() < 16) {
            RCLCPP_WARN(get_logger(), "Message too small, skipping");
            return;
        }

        std::int64_t publish_ts = 0;
        std::uint64_t seq = 0;
        std::uint32_t pub_id = 0;

        std::memcpy(&publish_ts, msg->data.data(),      sizeof(publish_ts));
        std::memcpy(&seq,        msg->data.data() + 8,  sizeof(seq));
        std::memcpy(&pub_id,     msg->data.data() + 12, sizeof(pub_id));

        // Mock computation: fixed sleep to simulate processing
        if (mock_delay_us_ > 0) {
            std::this_thread::sleep_for(std::chrono::microseconds(mock_delay_us_));
        }

        // Record (including warmup, we'll filter later)
        records_.push_back(LatencyRecord{
            .seq = seq,
            .publish_timestamp_ns = publish_ts,
            .receive_timestamp_ns = receive_ts,
            .latency_ns = receive_ts - publish_ts,
            .publisher_id = pub_id,
            .subscriber_id = node_id_
        });

        // Check if we've received enough
        const auto data_messages = records_.size() > warmup_ 
            ? records_.size() - warmup_ 
            : 0;

        if (data_messages >= expected_) {
            RCLCPP_INFO(get_logger(),
                "Subscriber [id=%u] received %zu data messages, finishing",
                node_id_, data_messages);
            write_csv();
            rclcpp::shutdown();
        }
    }

    void write_csv() {
        if (csv_written_) return;
        csv_written_ = true;

        const auto filename = output_path_ + "sub_" + std::to_string(node_id_) + ".csv";
        std::ofstream ofs(filename);
        if (!ofs.is_open()) {
            RCLCPP_ERROR(get_logger(), "Cannot open %s for writing", filename.c_str());
            return;
        }

        // Header
        ofs << "seq,publisher_id,subscriber_id,"
            << "publish_ts_ns,receive_ts_ns,latency_ns,"
            << "is_warmup,discovery_time_ns\n";

        for (std::size_t i = 0; i < records_.size(); ++i) {
            const auto& r = records_[i];
            const bool is_warmup = (i < warmup_);
            ofs << r.seq << ','
                << r.publisher_id << ','
                << r.subscriber_id << ','
                << r.publish_timestamp_ns << ','
                << r.receive_timestamp_ns << ','
                << r.latency_ns << ','
                << (is_warmup ? 1 : 0) << ','
                << discovery_time_ns_ << '\n';
        }

        RCLCPP_INFO(get_logger(),
            "Subscriber [id=%u] wrote %zu records to %s",
            node_id_, records_.size(), filename.c_str());
    }

    // --- Members ---
    rclcpp::Subscription<std_msgs::msg::ByteMultiArray>::SharedPtr subscription_;

    std::uint32_t node_id_ = 0;
    std::uint64_t mock_delay_us_ = 100;
    std::string output_path_;
    std::uint64_t warmup_ = 500;
    std::uint64_t expected_ = 5000;

    std::vector<LatencyRecord> records_;
    bool csv_written_ = false;
    bool first_message_received_ = false;
    std::int64_t discovery_start_ns_ = 0;
    std::int64_t discovery_time_ns_ = 0;
};

} // namespace benchmark

int main(int argc, char* argv[]) {
    rclcpp::init(argc, argv);
    rclcpp::spin(std::make_shared<benchmark::SubscriberNode>());
    rclcpp::shutdown();
    return 0;
}
