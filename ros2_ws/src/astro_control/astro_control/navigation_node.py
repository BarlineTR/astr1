#!/usr/bin/env python3
"""ASTRO V1 — Navigation & Obstacle Avoidance Node.

Subscribes to:
  /vision/faces    (std_msgs/String)  — JSON list of detected faces from face_detector_node
  /scan_filtered   (sensor_msgs/LaserScan) — Filtered Lidar scan from scan_filter_node

Publishes to:
  /wheel_cmds      (astro_base/WheelCmd)  — Differential drive motor speeds (RPM)
  /head_cmd        (astro_base/HeadCmd)   — Head yaw angle command (degrees)

Behaviour:
  1. IDLE     — No face detected for >2s: stop motors, return head to center.
  2. TRACKING — Face detected: pan head toward face, steer/drive body to approach at ~1m.
  3. ESTOP    — Lidar detects obstacle <40cm in front ±30°: override all motion with 0 RPM.

Thread safety: all shared state is guarded by a single threading.Lock.
"""
import json
import math
import threading

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import LaserScan
from std_msgs.msg import String

from astro_base.msg import HeadCmd, WheelCmd


class NavigationNode(Node):
    def __init__(self):
        super().__init__("navigation_node")

        # ── ROS Parameters ──────────────────────────────────────────────
        self.declare_parameter("image_width", 640)
        self.declare_parameter("target_face_width", 100)  # px at ~1 m
        self.declare_parameter("min_obstacle_dist", 0.4)  # meters (40 cm)
        self.declare_parameter("front_angle_deg", 30.0)   # ±30° frontal arc
        self.declare_parameter("max_rpm", 40.0)           # hard motor cap
        self.declare_parameter("face_timeout_s", 2.0)     # idle if no face this long
        self.declare_parameter("head_smooth_alpha", 0.15) # 0<α≤1 exponential smoothing

        self.img_width = int(self.get_parameter("image_width").value)
        self.target_face_width = float(self.get_parameter("target_face_width").value)
        self.min_obstacle_dist = float(self.get_parameter("min_obstacle_dist").value)
        self.front_angle_rad = math.radians(
            float(self.get_parameter("front_angle_deg").value)
        )
        self.max_rpm = float(self.get_parameter("max_rpm").value)
        self.face_timeout_s = float(self.get_parameter("face_timeout_s").value)
        self.head_smooth_alpha = float(self.get_parameter("head_smooth_alpha").value)

        # ── Publishers ──────────────────────────────────────────────────
        self.pub_wheel = self.create_publisher(WheelCmd, "/wheel_cmds", 10)
        self.pub_head = self.create_publisher(HeadCmd, "/head_cmd", 10)

        # ── Subscribers ─────────────────────────────────────────────────
        self.sub_faces = self.create_subscription(
            String, "/vision/faces", self._faces_callback, 10
        )
        self.sub_scan = self.create_subscription(
            LaserScan, "/scan_filtered", self._scan_callback, 10
        )

        # ── Shared state (guarded by _lock) ─────────────────────────────
        self._lock = threading.Lock()
        self._obstacle_detected: bool = False
        self._detected_face: dict | None = None
        self._last_face_time: rclpy.time.Time = self.get_clock().now()

        # ── Controller state ─────────────────────────────────────────────
        # Smoothed head yaw target (degrees).  Updated only inside control_loop.
        self._head_yaw_target: float = 0.0

        # ── 20 Hz control loop ───────────────────────────────────────────
        self._timer = self.create_timer(0.05, self._control_loop)

        self.get_logger().info(
            f"✅ [NavNode] Started — obstacle_dist={self.min_obstacle_dist}m  "
            f"max_rpm={self.max_rpm}  face_timeout={self.face_timeout_s}s"
        )

    # ──────────────────────────────────────────────────────────────────────
    # Subscriber callbacks  (run on ROS executor thread)
    # ──────────────────────────────────────────────────────────────────────

    def _faces_callback(self, msg: String) -> None:
        try:
            faces: list[dict] = json.loads(msg.data)
        except Exception as e:
            self.get_logger().warn(f"[NavNode] faces JSON parse error: {e}")
            return

        with self._lock:
            if faces:
                # Track the largest (= closest) face
                self._detected_face = max(faces, key=lambda f: f.get("width", 0))
                self._last_face_time = self.get_clock().now()
            else:
                self._detected_face = None

    def _scan_callback(self, msg: LaserScan) -> None:
        angle = msg.angle_min
        found = False
        for r in msg.ranges:
            if not (math.isnan(r) or math.isinf(r) or r <= 0.0):
                if -self.front_angle_rad <= angle <= self.front_angle_rad:
                    if r < self.min_obstacle_dist:
                        found = True
                        break
            angle += msg.angle_increment

        with self._lock:
            self._obstacle_detected = found

    # ──────────────────────────────────────────────────────────────────────
    # Control loop  (20 Hz timer, runs on ROS executor thread)
    # ──────────────────────────────────────────────────────────────────────

    def _control_loop(self) -> None:
        now = self.get_clock().now()

        # Snapshot shared state atomically
        with self._lock:
            obstacle = self._obstacle_detected
            face = self._detected_face
            elapsed = (now - self._last_face_time).nanoseconds / 1e9
            face_active = face is not None and elapsed < self.face_timeout_s

        left_rpm = 0.0
        right_rpm = 0.0

        if obstacle:
            # 🚨 EMERGENCY STOP — Lidar override
            self.get_logger().warn(
                "🚨 [NavNode] OBSTACLE — motors stopped.",
                throttle_duration_sec=1.0,
            )
            # Gradually return head to centre while stopped
            self._head_yaw_target = self._smooth(self._head_yaw_target, 0.0)

        elif face_active:
            # 👤 TRACKING — proportional controller
            face_cx = face["x"] + face["width"] / 2.0
            face_w = float(face["width"])

            # 1. Desired head yaw: map pixel error → degrees
            #    error_norm ∈ [-1, +1], scale by 50° half-range
            error_norm = (face_cx - self.img_width / 2.0) / (self.img_width / 2.0)
            desired_yaw = -error_norm * 50.0          # negative: face right → turn right
            desired_yaw = max(-60.0, min(60.0, desired_yaw))

            # 2. Exponential smoothing to eliminate head jitter
            self._head_yaw_target = self._smooth(self._head_yaw_target, desired_yaw)

            # 3. Steering RPM proportional to head yaw (body follows head)
            steer_rpm = self._head_yaw_target * 0.6

            # 4. Forward / backward approach speed
            width_error = self.target_face_width - face_w
            if width_error > 15:           # too far → approach
                fwd = min(20.0, width_error * 0.4)
            elif width_error < -15:        # too close → back off gently
                fwd = max(-12.0, width_error * 0.25)
            else:
                fwd = 0.0                  # comfortable distance, hover in place

            left_rpm = fwd - steer_rpm
            right_rpm = fwd + steer_rpm

        else:
            # 💤 IDLE — no face, no obstacle: stop and re-centre head
            self._head_yaw_target = self._smooth(self._head_yaw_target, 0.0)

        # ── Safety clamp ─────────────────────────────────────────────────
        left_rpm = max(-self.max_rpm, min(self.max_rpm, left_rpm))
        right_rpm = max(-self.max_rpm, min(self.max_rpm, right_rpm))

        # ── Publish ──────────────────────────────────────────────────────
        head_msg = HeadCmd()
        head_msg.angle_deg = float(self._head_yaw_target)
        self.pub_head.publish(head_msg)

        wheel_msg = WheelCmd()
        wheel_msg.left_rpm = float(left_rpm)
        wheel_msg.right_rpm = float(right_rpm)
        self.pub_wheel.publish(wheel_msg)

    # ──────────────────────────────────────────────────────────────────────
    # Helpers
    # ──────────────────────────────────────────────────────────────────────

    def _smooth(self, current: float, target: float) -> float:
        """First-order exponential smoothing: prevents sudden head/motor jerks."""
        return current + self.head_smooth_alpha * (target - current)


def main():
    rclpy.init()
    node = NavigationNode()
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
