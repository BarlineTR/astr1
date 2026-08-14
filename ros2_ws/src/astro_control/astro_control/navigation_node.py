#!/usr/bin/env python3
import json
import math
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import LaserScan
from std_msgs.msg import String
from astro_base.msg import WheelCmd, HeadCmd

class NavigationNode(Node):
    def __init__(self):
        super().__init__("navigation_node")
        
        # Parameters
        self.declare_parameter("image_width", 640)
        self.declare_parameter("target_face_width", 100)  # Face size (px) at desired distance (~1 meter)
        self.declare_parameter("min_obstacle_dist", 0.4)   # Stop if obstacle closer than 40cm
        self.declare_parameter("front_angle_deg", 30.0)    # Front scan window: -30 to +30 deg
        self.declare_parameter("max_rpm", 40.0)            # Maximum motor RPM limit for safety
        
        self.img_width = self.get_parameter("image_width").value
        self.target_face_width = self.get_parameter("target_face_width").value
        self.min_obstacle_dist = self.get_parameter("min_obstacle_dist").value
        self.front_angle_rad = math.radians(self.get_parameter("front_angle_deg").value)
        self.max_rpm = self.get_parameter("max_rpm").value
        
        # Publishers
        self.pub_wheel = self.create_publisher(WheelCmd, "/wheel_cmds", 10)
        self.pub_head = self.create_publisher(HeadCmd, "/head_cmd", 10)
        
        # Subscribers
        self.sub_faces = self.create_subscription(String, "/vision/faces", self.faces_callback, 10)
        self.sub_scan = self.create_subscription(LaserScan, "/scan_filtered", self.scan_callback, 10)
        
        # Internal States
        self.obstacle_detected = False
        self.last_face_time = self.get_clock().now()
        self.current_head_yaw = 0.0  # degrees
        self.target_head_yaw = 0.0   # degrees
        
        # Control Loop Timer (20Hz)
        self.timer = self.create_timer(0.05, self.control_loop)
        
        # Latest Face Info
        self.detected_face = None
        
        self.get_logger().info("✅ ASTRO V1 Navigation & Obstacle Avoidance Node Started.")

    def faces_callback(self, msg: String):
        try:
            faces = json.loads(msg.data)
            if faces:
                # Target the largest face (assumed to be the closest person)
                self.detected_face = max(faces, key=lambda f: f["width"])
                self.last_face_time = self.get_clock().now()
            else:
                self.detected_face = None
        except Exception as e:
            self.get_logger().warn(f"Failed to parse faces JSON: {e}")
            self.detected_face = None

    def scan_callback(self, msg: LaserScan):
        # Scan front field-of-view for any obstacle closer than threshold
        angle = msg.angle_min
        obstacle_found = False
        
        for r in msg.ranges:
            # Skip invalid scans (inf/nan)
            if math.isnan(r) or math.isinf(r) or r <= 0.0:
                angle += msg.angle_increment
                continue
                
            # If scan falls within our front arc window
            if -self.front_angle_rad <= angle <= self.front_angle_rad:
                if r < self.min_obstacle_dist:
                    obstacle_found = True
                    break
                    
            angle += msg.angle_increment
            
        self.obstacle_detected = obstacle_found

    def control_loop(self):
        now = self.get_clock().now()
        left_rpm = 0.0
        right_rpm = 0.0
        
        # Face detection timeout (2.0 seconds)
        face_active = self.detected_face is not None and (now - self.last_face_time).nanoseconds / 1e9 < 2.0
        
        if self.obstacle_detected:
            # 🚨 Emergency Collision Avoidance Override
            self.get_logger().warn("🚨 OBSTACLE DETECTED! Stopping motors.", throttle_duration_sec=1.0)
            left_rpm = 0.0
            right_rpm = 0.0
            # Center head back
            self.target_head_yaw = 0.0
        elif face_active:
            # 👤 Face Tracking Controller
            face = self.detected_face
            face_center_x = face["x"] + (face["width"] / 2.0)
            face_width = face["width"]
            
            # 1. Head Yaw Panning (Proportional to pixel offset from center)
            pixel_offset = face_center_x - (self.img_width / 2.0)
            # Map pixel error to head angle change (-10 to +10 degrees per step scaling)
            error_normalized = pixel_offset / (self.img_width / 2.0)
            
            # Smoothly adjust head target angle (panning head towards face)
            self.target_head_yaw -= error_normalized * 4.0
            self.target_head_yaw = max(-60.0, min(60.0, self.target_head_yaw))  # Limit head yaw to +/-60 deg
            
            # 2. Base Turn/Steering RPM (Align robot body with head angle)
            # Gain: 0.8 RPM per degree of head deflection
            steer_rpm = self.target_head_yaw * 0.8
            
            # 3. Base Forward RPM (Approach face if far away)
            # Distance error based on face width target
            width_error = self.target_face_width - face_width
            
            if width_error > 15:  # Too far, move forward
                # Proportional speed based on how far away we are
                forward_rpm = width_error * 0.4
                # Limit forward speed for safety
                forward_rpm = min(20.0, forward_rpm)
            elif width_error < -15:  # Too close, move back slowly
                forward_rpm = width_error * 0.3
                forward_rpm = max(-15.0, forward_rpm)
            else:
                forward_rpm = 0.0
                
            # Combine forward and steer (differential drive mixing)
            left_rpm = forward_rpm - steer_rpm
            right_rpm = forward_rpm + steer_rpm
        else:
            # 💤 Idle Mode: Return head to center, stop motors
            self.target_head_yaw = 0.0
            left_rpm = 0.0
            right_rpm = 0.0

        # Safety Limits
        left_rpm = max(-self.max_rpm, min(self.max_rpm, left_rpm))
        right_rpm = max(-self.max_rpm, min(self.max_rpm, right_rpm))
        
        # Publish head command (Yaw Angle)
        head_msg = HeadCmd()
        head_msg.angle_deg = self.target_head_yaw
        self.pub_head.publish(head_msg)
        
        # Publish motor speed commands
        wheel_msg = WheelCmd()
        wheel_msg.left_rpm = left_rpm
        wheel_msg.right_rpm = right_rpm
        self.pub_wheel.publish(wheel_msg)

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
