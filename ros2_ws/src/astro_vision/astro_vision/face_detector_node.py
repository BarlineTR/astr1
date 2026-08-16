#!/usr/bin/env python3
"""ASTRO V1 — Highly Reliable Face & Gaze Detection Node.

Features:
  - Frontal vs Profile Face Cascade Discrimination
  - Temporal smoothing / debounce filter (prevents single-frame dropouts)
  - Publishes:
      /vision/faces            (String JSON)
      /vision/person_detected  (Bool)
      /vision/looking_at_robot (Bool) — True if direct frontal gaze
      /vision/face_image       (Image)
"""

import json
from collections import deque
import cv2
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Image
from std_msgs.msg import Bool, String

try:
    from astro_vision.image_utils import bgr_to_imgmsg, imgmsg_to_bgr
except ImportError:
    from image_utils import bgr_to_imgmsg, imgmsg_to_bgr


class FaceDetectorNode(Node):
    def __init__(self):
        super().__init__("face_detector_node")
        self.declare_parameter("input_topic", "/oak/rgb/image_raw")
        self.declare_parameter("scale_factor", 1.1)
        self.declare_parameter("min_neighbors", 3)
        self.declare_parameter("min_size", 40)

        input_topic = self.get_parameter("input_topic").value
        self.scale_factor = float(self.get_parameter("scale_factor").value)
        self.min_neighbors = int(self.get_parameter("min_neighbors").value)
        self.min_size = int(self.get_parameter("min_size").value)

        # Load Frontal & Profile Cascades
        frontal_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        profile_path = cv2.data.haarcascades + "haarcascade_profileface.xml"

        self.frontal_cascade = cv2.CascadeClassifier(frontal_path)
        self.profile_cascade = cv2.CascadeClassifier(profile_path)

        # Temporal smoothing buffer for gaze (last 5 frames)
        self._gaze_history = deque(maxlen=6)
        self._person_history = deque(maxlen=6)

        # Publishers
        self.pub_faces = self.create_publisher(String, "/vision/faces", 10)
        self.pub_person = self.create_publisher(Bool, "/vision/person_detected", 10)
        self.pub_looking = self.create_publisher(Bool, "/vision/looking_at_robot", 10)
        self.pub_image = self.create_publisher(Image, "/vision/face_image", 10)

        self.sub = self.create_subscription(Image, input_topic, self.image_callback, 10)
        self.get_logger().info(f"👁️ [Gaze & Face Detector] Kararlı Bakış Tespiti Hazır! Dinleniyor: {input_topic}")

    def image_callback(self, msg: Image):
        try:
            frame = imgmsg_to_bgr(msg)
            if frame is None:
                return
        except Exception as e:
            self.get_logger().warn(f"Image conversion failed: {e}")
            return

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        
        # 1. Detect Frontal Faces (Looking at robot)
        frontal_faces = self.frontal_cascade.detectMultiScale(
            gray,
            scaleFactor=self.scale_factor,
            minNeighbors=self.min_neighbors,
            minSize=(self.min_size, self.min_size),
        )

        # 2. Detect Profile Faces (Looking away / turned head)
        profile_faces = self.profile_cascade.detectMultiScale(
            gray,
            scaleFactor=1.15,
            minNeighbors=3,
            minSize=(self.min_size, self.min_size),
        )

        instant_looking = len(frontal_faces) > 0
        instant_person = (len(frontal_faces) > 0) or (len(profile_faces) > 0)

        self._gaze_history.append(instant_looking)
        self._person_history.append(instant_person)

        # Temporal smoothing: True if detected in at least 2 of the last 6 frames
        smoothed_looking = (self._gaze_history.count(True) >= 2)
        smoothed_person = (self._person_history.count(True) >= 2)

        face_list = []
        for x, y, w, h in frontal_faces:
            face_list.append({
                "x": int(x), "y": int(y), "width": int(w), "height": int(h),
                "type": "frontal", "looking_at_robot": True
            })
            cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 255, 0), 2)
            cv2.putText(frame, "BANA BAKIYOR", (x, y - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)

        for x, y, w, h in profile_faces:
            if not instant_looking:
                face_list.append({
                    "x": int(x), "y": int(y), "width": int(w), "height": int(h),
                    "type": "profile", "looking_at_robot": False
                })
                cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 140, 255), 2)
                cv2.putText(frame, "YANA BAKIYOR", (x, y - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 140, 255), 2)

        # 1. Publish Faces List
        faces_msg = String()
        faces_msg.data = json.dumps(face_list)
        self.pub_faces.publish(faces_msg)

        # 2. Publish Person Detected
        person_msg = Bool()
        person_msg.data = smoothed_person
        self.pub_person.publish(person_msg)

        # 3. Publish Looking At Robot (Direct Gaze)
        looking_msg = Bool()
        looking_msg.data = smoothed_looking
        self.pub_looking.publish(looking_msg)

        # 4. Debug Image
        out_image = bgr_to_imgmsg(frame, msg.header)
        self.pub_image.publish(out_image)


def main(args=None):
    rclpy.init(args=args)
    node = FaceDetectorNode()
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
