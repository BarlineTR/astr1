#!/usr/bin/env python3
import json

import cv2
import rclpy
from cv_bridge import CvBridge
from rclpy.node import Node
from sensor_msgs.msg import Image
from std_msgs.msg import Bool, String


class FaceDetectorNode(Node):
    def __init__(self):
        super().__init__("face_detector_node")
        self.declare_parameter("input_topic", "/oak/rgb/image_raw")
        self.declare_parameter("scale_factor", 1.1)
        self.declare_parameter("min_neighbors", 5)
        self.declare_parameter("min_size", 30)

        input_topic = self.get_parameter("input_topic").value
        self.scale_factor = float(self.get_parameter("scale_factor").value)
        self.min_neighbors = int(self.get_parameter("min_neighbors").value)
        self.min_size = int(self.get_parameter("min_size").value)

        cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        self.face_cascade = cv2.CascadeClassifier(cascade_path)
        if self.face_cascade.empty():
            self.get_logger().error(f"Failed to load cascade: {cascade_path}")

        self.bridge = CvBridge()
        self.pub_faces = self.create_publisher(String, "/vision/faces", 10)
        self.pub_person = self.create_publisher(Bool, "/vision/person_detected", 10)
        self.pub_image = self.create_publisher(Image, "/vision/face_image", 10)

        self.sub = self.create_subscription(
            Image, input_topic, self.image_callback, 10
        )
        self.get_logger().info(f"Face detector listening on {input_topic}")

    def image_callback(self, msg: Image):
        try:
            frame = self.bridge.imgmsg_to_cv2(msg, desired_encoding="bgr8")
        except Exception as e:
            self.get_logger().warn(f"Image conversion failed: {e}")
            return

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = self.face_cascade.detectMultiScale(
            gray,
            scaleFactor=self.scale_factor,
            minNeighbors=self.min_neighbors,
            minSize=(self.min_size, self.min_size),
        )

        face_list = []
        for x, y, w, h in faces:
            face_list.append(
                {
                    "x": int(x),
                    "y": int(y),
                    "width": int(w),
                    "height": int(h),
                    "confidence": 1.0,
                }
            )
            cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 255, 0), 2)

        faces_msg = String()
        faces_msg.data = json.dumps(face_list)
        self.pub_faces.publish(faces_msg)

        person_msg = Bool()
        person_msg.data = len(face_list) > 0
        self.pub_person.publish(person_msg)

        try:
            out_image = self.bridge.cv2_to_imgmsg(frame, encoding="bgr8")
            out_image.header = msg.header
            self.pub_image.publish(out_image)
        except Exception as e:
            self.get_logger().debug(f"Output image publish failed: {e}")


def main():
    rclpy.init()
    node = FaceDetectorNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    node.destroy_node()
    rclpy.shutdown()


if __name__ == "__main__":
    main()
