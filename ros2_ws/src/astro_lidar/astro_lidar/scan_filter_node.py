#!/usr/bin/env python3
import math

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import LaserScan


class ScanFilterNode(Node):
    def __init__(self):
        super().__init__("scan_filter_node")
        self.declare_parameter("range_min", 0.15)
        self.declare_parameter("range_max", 12.0)
        self.declare_parameter("filter_nan", True)
        self.declare_parameter("input_topic", "/scan")
        self.declare_parameter("output_topic", "/scan_filtered")

        self.range_min = self.get_parameter("range_min").value
        self.range_max = self.get_parameter("range_max").value
        self.filter_nan = self.get_parameter("filter_nan").value
        input_topic = self.get_parameter("input_topic").value
        output_topic = self.get_parameter("output_topic").value

        self.pub = self.create_publisher(LaserScan, output_topic, 10)
        self.sub = self.create_subscription(
            LaserScan, input_topic, self.scan_callback, 10
        )
        self.get_logger().info(
            f"Filtering {input_topic} -> {output_topic} "
            f"(range [{self.range_min}, {self.range_max}] m)"
        )

    def scan_callback(self, msg: LaserScan):
        filtered = LaserScan()
        filtered.header = msg.header
        filtered.angle_min = msg.angle_min
        filtered.angle_max = msg.angle_max
        filtered.angle_increment = msg.angle_increment
        filtered.time_increment = msg.time_increment
        filtered.scan_time = msg.scan_time
        filtered.range_min = self.range_min
        filtered.range_max = self.range_max
        filtered.ranges = []
        filtered.intensities = []

        has_intensity = len(msg.intensities) == len(msg.ranges)

        for i, r in enumerate(msg.ranges):
            if self.filter_nan and (
                math.isnan(r) or math.isinf(r) or r <= 0.0
            ):
                filtered.ranges.append(float("inf"))
                if has_intensity:
                    filtered.intensities.append(0.0)
                continue

            if r < self.range_min or r > self.range_max:
                filtered.ranges.append(float("inf"))
                if has_intensity:
                    filtered.intensities.append(0.0)
            else:
                filtered.ranges.append(r)
                if has_intensity:
                    filtered.intensities.append(msg.intensities[i])

        self.pub.publish(filtered)


def main():
    rclpy.init()
    node = ScanFilterNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
