#!/usr/bin/env python3
"""ASTRO V1 — USB webcam yayıncısı.

OAK-D takılı olmadığında (ya da masaüstünde geliştirirken) sıradan bir USB
kamerayı OAK-D ile aynı konuya yayınlar; böylece face_detector_node ve
ai_brain_node'da hiçbir şey değişmeden çalışır.

    ros2 run astro_vision webcam_publisher_node
    ros2 launch astro_vision camera.launch.py source:=webcam

OAK-D takılıyken bu düğümü çalıştırmayın: aynı konuya iki yayıncı olur.
"""
import cv2
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Image
from std_msgs.msg import Header

try:
    from astro_vision.image_utils import bgr_to_imgmsg
except ImportError:
    from image_utils import bgr_to_imgmsg


class WebcamPublisherNode(Node):
    def __init__(self):
        super().__init__("webcam_publisher_node")
        self.declare_parameter("device", 0)
        self.declare_parameter("output_topic", "/oak/rgb/image_raw")
        self.declare_parameter("width", 640)
        self.declare_parameter("height", 480)
        self.declare_parameter("fps", 15.0)
        self.declare_parameter("frame_id", "camera_link")

        device = int(self.get_parameter("device").value)
        topic = self.get_parameter("output_topic").value
        fps = float(self.get_parameter("fps").value)
        self.frame_id = self.get_parameter("frame_id").value

        self.cap = cv2.VideoCapture(device)
        if not self.cap.isOpened():
            self.get_logger().error(
                f"❌ [Webcam] /dev/video{device} açılamadı. "
                "Kamera takılı mı? Farklı bir indeks için: --ros-args -p device:=1"
            )
            self.cap = None
        else:
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, int(self.get_parameter("width").value))
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, int(self.get_parameter("height").value))
            actual_w = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            actual_h = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            self.get_logger().info(
                f"📷 [Webcam] /dev/video{device} → {topic} ({actual_w}x{actual_h} @ {fps:g} Hz)"
            )

        self.pub = self.create_publisher(Image, topic, 10)
        self.create_timer(1.0 / max(fps, 1.0), self._tick)
        self._warned = False

    def _tick(self):
        if self.cap is None:
            return
        ok, frame = self.cap.read()
        if not ok:
            if not self._warned:
                self.get_logger().warn("Kameradan kare okunamıyor")
                self._warned = True
            return
        self._warned = False

        header = Header()
        header.stamp = self.get_clock().now().to_msg()
        header.frame_id = self.frame_id
        self.pub.publish(bgr_to_imgmsg(frame, header))

    def destroy_node(self):
        if self.cap is not None:
            self.cap.release()
        super().destroy_node()


def main():
    rclpy.init()
    node = WebcamPublisherNode()
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
