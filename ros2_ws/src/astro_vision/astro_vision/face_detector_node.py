#!/usr/bin/env python3
"""ASTRO V1 — Face & Gaze Detection Node.

Publishes:
  /vision/faces            (String JSON) — Bounding boxes of detected faces
  /vision/person_detected  (Bool)        — True if any face/person in frame
  /vision/looking_at_robot (Bool)        — True if person is making direct eye contact with camera
  /vision/face_image       (Image)       — Debug annotated visual frame
"""

import json
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
        self.declare_parameter("min_neighbors", 4)
        self.declare_parameter("min_size", 40)

        input_topic = self.get_parameter("input_topic").value
        self.scale_factor = float(self.get_parameter("scale_factor").value)
        self.min_neighbors = int(self.get_parameter("min_neighbors").value)
        self.min_size = int(self.get_parameter("min_size").value)

        # Load Face & Eye Cascades for direct gaze / eye-contact detection
        face_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        eye_path = cv2.data.haarcascades + "haarcascade_eye.xml"

        self.face_cascade = cv2.CascadeClassifier(face_path)
        self.eye_cascade = cv2.CascadeClassifier(eye_path)

        if self.face_cascade.empty():
            self.get_logger().error(f"Failed to load face cascade: {face_path}")

        # Publishers
        self.pub_faces = self.create_publisher(String, "/vision/faces", 10)
        self.pub_person = self.create_publisher(Bool, "/vision/person_detected", 10)
        self.pub_looking = self.create_publisher(Bool, "/vision/looking_at_robot", 10)
        self.pub_image = self.create_publisher(Image, "/vision/face_image", 10)

        self.sub = self.create_subscription(Image, input_topic, self.image_callback, 10)
        self.get_logger().info(f"👁️ [Gaze & Face Detector] Aktif! Dinleniyor: {input_topic}")

    def image_callback(self, msg: Image):
        try:
            frame = imgmsg_to_bgr(msg)
            if frame is None:
                return
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
        is_looking_at_camera = False

        for x, y, w, h in faces:
            face_roi_gray = gray[y:y + h, x:x + w]
            
            # Gaze verification: Detect eyes inside the upper face region
            upper_face = face_roi_gray[0:int(h * 0.65), :]
            eyes = self.eye_cascade.detectMultiScale(
                upper_face,
                scaleFactor=1.1,
                minNeighbors=3,
                minSize=(15, 15)
            )

            # Direct frontal face + eyes visible indicates looking at robot
            direct_gaze = len(eyes) >= 1

            if direct_gaze:
                is_looking_at_camera = True

            face_list.append({
                "x": int(x),
                "y": int(y),
                "width": int(w),
                "height": int(h),
                "eyes_detected": int(len(eyes)),
                "looking_at_robot": direct_gaze
            })

            # Draw visual debug overlays
            color = (0, 255, 0) if direct_gaze else (0, 165, 255)
            cv2.rectangle(frame, (x, y), (x + w, y + h), color, 2)
            label = "BANA BAKIYOR" if direct_gaze else "YANA BAKIYOR"
            cv2.putText(frame, label, (x, y - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)

            for ex, ey, ew, eh in eyes:
                cv2.rectangle(frame, (x + ex, y + ey), (x + ex + ew, y + ey + eh), (255, 255, 0), 1)

        # 1. Publish Faces List
        faces_msg = String()
        faces_msg.data = json.dumps(face_list)
        self.pub_faces.publish(faces_msg)

        # 2. Publish Person Detected
        person_msg = Bool()
        person_msg.data = len(face_list) > 0
        self.pub_person.publish(person_msg)

        # 3. Publish Looking At Robot (Eye Contact)
        looking_msg = Bool()
        looking_msg.data = is_looking_at_camera
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
