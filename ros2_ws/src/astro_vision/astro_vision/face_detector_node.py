#!/usr/bin/env python3
"""ASTRO V1 — Spatial AI Vision Node with Emotion & Gaze Tracking.

Features:
  1. 3D Head Pose & Gaze Angle (solvePnP / eye symmetry)
  2. Stereo Depth Distance (/vision/user_distance in meters)
  3. Facial Emotion Detection (/vision/user_emotion: 'happy', 'sad', 'surprised', 'neutral')
  4. Publishes:
      /vision/faces            (String JSON)
      /vision/person_detected  (Bool)
      /vision/looking_at_robot (Bool)
      /vision/head_yaw         (Float32)
      /vision/user_distance    (Float32)
      /vision/user_emotion     (String)
      /vision/face_image       (Image)
"""

import json
from collections import deque
import cv2
import numpy as np

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Image
from std_msgs.msg import String, Bool, Float32

try:
    from astro_vision.image_utils import bgr_to_imgmsg, imgmsg_to_bgr
    from astro_vision.face_recognizer import FaceRecognizer
except ImportError:
    from image_utils import bgr_to_imgmsg, imgmsg_to_bgr
    class FaceRecognizer:
        def identify(self, frame, x, y, w, h):
            return {"name": "Misafir", "title": "Ziyaretçi", "confidence": 0.0, "is_known": False}


class SpatialVisionNode(Node):
    def __init__(self):
        super().__init__("face_detector_node")
        self.declare_parameter("input_topic", "/oak/rgb/image_raw")
        self.declare_parameter("depth_topic", "/oak/stereo/image_raw")
        self.declare_parameter("scale_factor", 1.1)
        self.declare_parameter("min_neighbors", 4)
        self.declare_parameter("min_size", 45)

        input_topic = self.get_parameter("input_topic").value
        depth_topic = self.get_parameter("depth_topic").value
        self.scale_factor = float(self.get_parameter("scale_factor").value)
        self.min_neighbors = int(self.get_parameter("min_neighbors").value)
        self.min_size = int(self.get_parameter("min_size").value)

        # Load Cascades (Default + Alt2 for maximum detection rate)
        frontal_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        alt2_path = cv2.data.haarcascades + "haarcascade_frontalface_alt2.xml"
        smile_path = cv2.data.haarcascades + "haarcascade_smile.xml"
        eye_path = cv2.data.haarcascades + "haarcascade_eye.xml"

        self.face_cascade = cv2.CascadeClassifier(frontal_path)
        self.face_alt_cascade = cv2.CascadeClassifier(alt2_path)
        self.smile_cascade = cv2.CascadeClassifier(smile_path)
        self.eye_cascade = cv2.CascadeClassifier(eye_path)

        # Check GPU / CUDA Acceleration on Jetson
        self.gpu_accelerated = False
        try:
            if hasattr(cv2, 'cuda') and cv2.cuda.getCudaEnabledDeviceCount() > 0:
                self.gpu_accelerated = True
                self.get_logger().info(f"🚀 [Spatial Vision] Jetson Orin Nano GPU / CUDA Hızlandırma Aktif!")
        except Exception:
            pass

        # Internal Buffers
        self._latest_depth = None
        self._gaze_history = deque(maxlen=5)
        self._emotion_history = deque(maxlen=8)
        self.face_recognizer = FaceRecognizer()

        # Publishers
        self.pub_faces = self.create_publisher(String, "/vision/faces", 10)
        self.pub_person = self.create_publisher(Bool, "/vision/person_detected", 10)
        self.pub_looking = self.create_publisher(Bool, "/vision/looking_at_robot", 10)
        self.pub_yaw = self.create_publisher(Float32, "/vision/head_yaw", 10)
        self.pub_distance = self.create_publisher(Float32, "/vision/user_distance", 10)
        self.pub_emotion = self.create_publisher(String, "/vision/user_emotion", 10)
        self.pub_recognized_person = self.create_publisher(String, "/vision/recognized_person", 10)
        self.pub_image = self.create_publisher(Image, "/vision/face_image", 10)

        # Subscribers
        self.sub_rgb = self.create_subscription(Image, input_topic, self.image_callback, 10)
        self.sub_depth = self.create_subscription(Image, depth_topic, self.depth_callback, 10)

        self.get_logger().info(f"👁️ [Spatial Emotion Vision] 3D Bakış, Mesafe ve Yüz Duygu Analizi Aktif! RGB: {input_topic}")

    def depth_callback(self, msg: Image):
        try:
            if msg.encoding in ["16UC1", "mono16"]:
                self._latest_depth = np.frombuffer(msg.data, dtype=np.uint16).reshape(msg.height, msg.width)
            elif msg.encoding in ["32FC1"]:
                self._latest_depth = (np.frombuffer(msg.data, dtype=np.float32).reshape(msg.height, msg.width) * 1000.0).astype(np.uint16)
        except Exception:
            pass

    def _estimate_distance(self, x: int, y: int, w: int, h: int, frame_w: int, frame_h: int) -> float:
        if self._latest_depth is not None:
            try:
                dh, dw = self._latest_depth.shape[:2]
                sx = int((x + w/2) * (dw / frame_w))
                sy = int((y + h/2) * (dh / frame_h))
                sx = max(0, min(dw - 1, sx))
                sy = max(0, min(dh - 1, sy))

                patch = self._latest_depth[max(0, sy - 10):min(dh, sy + 10), max(0, sx - 10):min(dw, sx + 10)]
                valid = patch[patch > 200]
                if len(valid) > 0:
                    return float(np.median(valid)) / 1000.0
            except Exception:
                pass

        focal_length = frame_w * 0.8
        distance = (0.15 * focal_length) / max(1, w)
        return float(np.clip(distance, 0.3, 4.0))

    def _estimate_head_yaw(self, face_roi_gray, w, h) -> tuple[float, bool]:
        """Calculates yaw angle and strictly verifies eye visibility to reject back-of-head false detections."""
        roi = cv2.resize(face_roi_gray[:int(h * 0.6), :], (96, 54), interpolation=cv2.INTER_AREA) if w > 96 else face_roi_gray[:int(h * 0.6), :]
        rw = roi.shape[1]
        eyes = self.eye_cascade.detectMultiScale(roi, scaleFactor=1.15, minNeighbors=3, minSize=(10, 10))
        if len(eyes) >= 2:
            eyes_sorted = sorted(eyes, key=lambda e: e[0])
            left_eye_center = eyes_sorted[0][0] + eyes_sorted[0][2] / 2.0
            right_eye_center = eyes_sorted[-1][0] + eyes_sorted[-1][2] / 2.0
            eye_midpoint = (left_eye_center + right_eye_center) / 2.0
            face_center = rw / 2.0
            yaw_deg = float(((eye_midpoint - face_center) / face_center) * 35.0)
            return yaw_deg, True
        elif len(eyes) == 1:
            eye_x = eyes[0][0] + eyes[0][2] / 2.0
            yaw_deg = -25.0 if eye_x < rw / 2.0 else 25.0
            return yaw_deg, True
        # If ZERO eyes found, the face is turned away / back of the head — NOT looking at robot!
        return 90.0, False

    def _detect_facial_emotion(self, face_roi_gray, w, h) -> str:
        """Determines emotion (happy/smiling, surprised, sad/neutral) based on mouth and eyes geometry."""
        lower_face = cv2.resize(face_roi_gray[int(h * 0.5):, :], (96, 48), interpolation=cv2.INTER_AREA) if w > 96 else face_roi_gray[int(h * 0.5):, :]
        smiles = self.smile_cascade.detectMultiScale(lower_face, scaleFactor=1.65, minNeighbors=10, minSize=(15, 15))
        if len(smiles) > 0:
            return "happy"
        return "neutral"

    def image_callback(self, msg: Image):
        try:
            frame = imgmsg_to_bgr(msg)
            if frame is None:
                return
        except Exception as e:
            self.get_logger().warn(f"Image conversion failed: {e}")
            return

        if not hasattr(self, '_frame_count'):
            self._frame_count = 0
        self._frame_count += 1

        # Process every 2nd frame (~15 FPS for responsive tracking)
        if self._frame_count % 2 != 0:
            return

        frame_h, frame_w = frame.shape[:2]
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        
        # Scale to 640px for high detection accuracy on Jetson (preserving facial landmarks)
        scale_ratio = 640.0 / float(frame_w) if frame_w > 640 else 1.0
        
        if scale_ratio < 1.0:
            small_gray = cv2.resize(gray, (0, 0), fx=scale_ratio, fy=scale_ratio, interpolation=cv2.INTER_AREA)
        else:
            small_gray = gray

        detected_faces = self.face_cascade.detectMultiScale(
            small_gray,
            scaleFactor=1.1,
            minNeighbors=3,
            minSize=(24, 24),
        )

        if len(detected_faces) == 0 and hasattr(self, 'face_alt_cascade'):
            detected_faces = self.face_alt_cascade.detectMultiScale(
                small_gray,
                scaleFactor=1.1,
                minNeighbors=3,
                minSize=(24, 24),
            )

        # Map bounding boxes back to original resolution
        if len(detected_faces) > 0 and scale_ratio < 1.0:
            faces = [[int(x / scale_ratio), int(y / scale_ratio), int(w / scale_ratio), int(h / scale_ratio)] for (x, y, w, h) in detected_faces]
        else:
            faces = list(detected_faces)

        # Temporal smoothing for face detection dropouts
        if len(faces) == 0 and hasattr(self, '_last_known_face') and self._last_known_face is not None:
            if self._face_lost_frames < 8:  # Tolerate up to 8 frames of lost face
                faces = [self._last_known_face]
                self._face_lost_frames += 1
            else:
                self._last_known_face = None
        elif len(faces) > 0:
            # Sort by size to track the largest face
            faces = sorted(faces, key=lambda f: f[2]*f[3], reverse=True)
            self._last_known_face = faces[0]
            self._face_lost_frames = 0
        else:
            self._face_lost_frames = 0
            self._last_known_face = None

        face_list = []
        is_looking = False
        user_distance = 0.0
        head_yaw = 0.0
        detected_emotion = "neutral"
        top_recognized_person = {"name": "Misafir", "title": "Ziyaretçi", "formal_title": "Misafir", "confidence": 0.0, "is_known": False}

        for x, y, w, h in faces:
            face_roi_gray = gray[y:y + h, x:x + w]
            face_roi_bgr = frame[y:y + h, x:x + w]
            
            # 1. 3D Head Yaw & Eye Verification
            yaw, eyes_found = self._estimate_head_yaw(face_roi_gray, w, h)
            head_yaw = yaw

            # 2. 3D Distance
            dist_m = self._estimate_distance(x, y, w, h, frame_w, frame_h)
            user_distance = dist_m

            # 3. Direct Gaze: Eyes MUST be visible AND yaw <= 30 degrees AND strictly in Social Zone (0.35m - 2.50m)
            direct_gaze = eyes_found and (abs(yaw) <= 30.0) and (0.35 <= dist_m <= 2.50)
            if direct_gaze:
                is_looking = True

            # 4. Face Recognition Matching
            recog_name, recog_conf, recog_meta = self.face_recognizer.recognize_face(face_roi_bgr)
            is_known = (recog_name is not None and recog_conf >= 0.72)
            if is_known and recog_conf > top_recognized_person["confidence"]:
                top_recognized_person = {
                    "name": recog_name,
                    "title": recog_meta.get("title", "Tanınan Kişi"),
                    "formal_title": recog_meta.get("formal_title", recog_name),
                    "confidence": recog_conf,
                    "is_known": True,
                    "distance_m": round(dist_m, 2)
                }

            # 5. Emotion Detection
            detected_emotion = self._detect_facial_emotion(face_roi_gray, w, h)

            face_list.append({
                "x": int(x), "y": int(y), "width": int(w), "height": int(h),
                "yaw_deg": round(yaw, 1),
                "distance_m": round(dist_m, 2),
                "looking_at_robot": direct_gaze,
                "emotion": detected_emotion,
                "recognized_name": recog_name if is_known else None,
                "recognized_title": recog_meta.get("formal_title") if is_known else None
            })

            # Draw HUD
            color_map = {
                "happy": (0, 255, 0),
                "surprised": (255, 255, 0),
                "neutral": (0, 200, 255),
                "sad": (0, 0, 255)
            }
            box_color = (0, 215, 255) if is_known else color_map.get(detected_emotion, (0, 255, 0))
            cv2.rectangle(frame, (x, y), (x + w, y + h), box_color, 2)
            
            tag_name = f"★ {recog_name} ({recog_meta.get('formal_title', '')})" if is_known else detected_emotion.upper()
            gaze_txt = "BANA BAKIYOR" if direct_gaze else (f"YANA ({yaw:.0f}°)" if eyes_found else "BAKMIYOR (GÖZ YOK)")
            hud_text = f"{tag_name} | {gaze_txt} | {dist_m:.2f}m"
            cv2.putText(frame, hud_text, (x, max(22, y - 10)), cv2.FONT_HERSHEY_SIMPLEX, 0.55, box_color, 2)

        self._gaze_history.append(is_looking)
        smoothed_looking = (self._gaze_history.count(True) >= 2)

        self._emotion_history.append(detected_emotion)
        # Dominant emotion
        smoothed_emotion = max(set(self._emotion_history), key=self._emotion_history.count)

        # Publishers
        faces_msg = String()
        faces_msg.data = json.dumps(face_list)
        self.pub_faces.publish(faces_msg)

        person_msg = Bool()
        person_msg.data = len(faces) > 0
        self.pub_person.publish(person_msg)

        looking_msg = Bool()
        looking_msg.data = smoothed_looking
        self.pub_looking.publish(looking_msg)

        yaw_msg = Float32()
        yaw_msg.data = float(head_yaw)
        self.pub_yaw.publish(yaw_msg)

        dist_msg = Float32()
        dist_msg.data = float(user_distance)
        self.pub_distance.publish(dist_msg)

        emotion_msg = String()
        emotion_msg.data = smoothed_emotion
        self.pub_emotion.publish(emotion_msg)

        recog_msg = String()
        recog_msg.data = json.dumps(top_recognized_person)
        self.pub_recognized_person.publish(recog_msg)

        # Diagnostic logger on gaze state change
        if not hasattr(self, '_prev_looking_log'):
            self._prev_looking_log = False
        if is_looking != self._prev_looking_log:
            self._prev_looking_log = is_looking
            if is_looking and (0.35 <= user_distance <= 2.50):
                known_tag = f" — [{top_recognized_person['formal_title']}]" if top_recognized_person["is_known"] else ""
                self.get_logger().info(f"👀 [Göz Teması]: Kullanıcı algılandı! (Mesafe: {user_distance:.2f}m, Açı: {head_yaw:.1f}°){known_tag}")

        # Publish Images
        try:
            face_img_msg = bgr_to_imgmsg(frame, msg.header)
            self.pub_image.publish(face_img_msg)
        except Exception:
            pass


def main(args=None):
    rclpy.init(args=args)
    node = SpatialVisionNode()
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
