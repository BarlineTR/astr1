#!/usr/bin/env python3
"""ASTRO V1 — Real-Time Performance & Diagnostics ROS 2 Node."""

import json
import logging

_LOG = logging.getLogger(__name__)

import rclpy
from rclpy.node import Node
from std_msgs.msg import String

try:
    from astro_ai.performance_profiler import PerformanceProfiler
except ImportError:
    from performance_profiler import PerformanceProfiler


class ProfilerNode(Node):
    def __init__(self):
        super().__init__("profiler_node")

        self.profiler = PerformanceProfiler()
        self.pub_diagnostics = self.create_publisher(String, "/astro/diagnostics", 10)

        # Publish diagnostics every 5.0 seconds
        self.create_timer(5.0, self._publish_diagnostics)
        self.get_logger().info("📊 [Profiler Node] Jetson Donanım ve Pipeline İzleme Aktif (/astro/diagnostics)")

    def _publish_diagnostics(self):
        hw = self.profiler.get_hardware_metrics()
        msg = String()
        msg.data = json.dumps(hw)
        self.pub_diagnostics.publish(msg)


def main(args=None):
    rclpy.init(args=args)
    node = ProfilerNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt as _exc:
        _LOG.debug("main: yok sayılan hata (%s)", _exc)
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
