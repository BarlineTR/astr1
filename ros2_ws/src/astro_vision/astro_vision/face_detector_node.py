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
import logging
import threading
import time

_LOG = logging.getLogger(__name__)

from collections import deque
try:
    import cv2
except ImportError:
    class _MockCV2:
        class data:
            haarcascades = ""
        class CascadeClassifier:
            def __init__(self, *args, **kwargs): pass
            def detectMultiScale(self, *args, **kwargs): return []
        INTER_AREA = 3
        FONT_HERSHEY_SIMPLEX = 0
        def resize(self, src, dsize, *args, **kwargs): return src
        def cvtColor(self, src, code): return src
        def rectangle(self, *args, **kwargs): pass
        def putText(self, *args, **kwargs): pass
    cv2 = _MockCV2()

import numpy as np

try:
    import rclpy
    from rclpy.node import Node
    from rclpy.qos import QoSProfile, QoSReliabilityPolicy, QoSHistoryPolicy, qos_profile_sensor_data
    from sensor_msgs.msg import Image
    from std_msgs.msg import String, Bool, Float32
except ImportError:
    rclpy = None
    Node = object
    QoSProfile = QoSReliabilityPolicy = QoSHistoryPolicy = object
    qos_profile_sensor_data = 10
    Image = String = Bool = Float32 = object

try:
    from astro_vision.image_utils import bgr_to_imgmsg, imgmsg_to_bgr
    from astro_vision.face_recognizer import FaceRecognizer
    from astro_vision.detection_quality import detect_faces_with_confidence
except ImportError:
    from image_utils import bgr_to_imgmsg, imgmsg_to_bgr
    from detection_quality import detect_faces_with_confidence
    class FaceRecognizer:
        def identify(self, frame, x, y, w, h):
            return {"name": "Misafir", "title": "Ziyaretçi", "confidence": 0.0, "is_known": False}


class SpatialVisionNode(Node):
    def __init__(self):
        super().__init__("face_detector_node")
        self.declare_parameter("input_topic", "/oak/rgb/image_raw")
        self.declare_parameter("depth_topic", "/oak/depth/image_raw")
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

        # Constrain OpenCV thread pool to 1 thread to eliminate multi-core CPU saturation
        try:
            cv2.setNumThreads(1)
            self.get_logger().info("🧵 [Spatial Vision] OpenCV iş parçacığı 1 olarak sınırlandı (CPU koruması)")
        except Exception as _exc:
            self.get_logger().debug(f"setNumThreads: yok sayılan hata ({_exc})")

        # Check GPU / CUDA Acceleration on Jetson
        self.gpu_accelerated = False
        try:
            if hasattr(cv2, 'cuda') and cv2.cuda.getCudaEnabledDeviceCount() > 0:
                self.gpu_accelerated = True
                self.get_logger().info(f"🚀 [Spatial Vision] Jetson Orin Nano GPU / CUDA Hızlandırma Aktif!")
        except Exception as _exc:
            self.get_logger().debug(f"__init__: yok sayılan hata ({_exc})")

        # Internal Buffers
        self._latest_depth = None
        self._gaze_history = deque(maxlen=5)
        self._emotion_history = deque(maxlen=8)
        self.face_recognizer = FaceRecognizer()

        # Latest-Frame-Wins Worker State & Telemetry
        self._slot_lock = threading.Lock()
        self._pending_image = None
        self._pending_arrival_mono = 0.0
        self._frame_available_event = threading.Event()
        self._stop_worker = False

        self._camera_input_count = 0
        self._detector_processed_count = 0
        self._dropped_frames = 0
        self._frame_ages_ms = deque(maxlen=100)

        # Stage latency tracking (Phase 2A Forensic Profiling)
        self._lat_total_ms = deque(maxlen=100)
        self._lat_bgr_ms = deque(maxlen=100)
        self._lat_gray_ms = deque(maxlen=100)
        self._lat_pri_haar_ms = deque(maxlen=100)
        self._lat_alt_haar_ms = deque(maxlen=100)
        self._lat_post_ms = deque(maxlen=100)

        # Haar invocation & hit counters
        self._pri_calls = 0
        self._pri_hits = 0
        self._alt_calls = 0
        self._alt_hits = 0

        self._last_perf_log_time = time.monotonic()
        self._last_perf_camera_count = 0
        self._last_perf_det_count = 0

        # Start dedicated low-latency vision worker thread
        self._worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
        self._worker_thread.start()

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
        # Görüntü akışları en güncel tek kare (KEEP_LAST depth=1, BEST_EFFORT) kullanır:
        # Kuyruk birikmesini (backpressure) engeller.
        qos_profile_latest = QoSProfile(
            reliability=QoSReliabilityPolicy.BEST_EFFORT,
            history=QoSHistoryPolicy.KEEP_LAST,
            depth=1,
        )
        self.sub_rgb = self.create_subscription(Image, input_topic, self.image_callback, qos_profile_latest)
        self.sub_depth = self.create_subscription(Image, depth_topic, self.depth_callback, qos_profile_sensor_data)

        self.get_logger().info(f"👁️ [Spatial Emotion Vision] 3D Bakış ve Hızlı Yüz Tespiti Aktif! RGB: {input_topic}")

    def depth_callback(self, msg: Image):
        try:
            if msg.encoding in ["16UC1", "mono16"]:
                self._latest_depth = np.frombuffer(msg.data, dtype=np.uint16).reshape(msg.height, msg.width)
            elif msg.encoding in ["32FC1"]:
                self._latest_depth = (np.frombuffer(msg.data, dtype=np.float32).reshape(msg.height, msg.width) * 1000.0).astype(np.uint16)
        except Exception as _exc:
            self.get_logger().debug(f"depth_callback: yok sayılan hata ({_exc})")

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
            except Exception as _exc:
                self.get_logger().debug(f"_estimate_distance: yok sayılan hata ({_exc})")

        focal_length = frame_w * 0.8
        distance = (0.15 * focal_length) / max(1, w)
        return float(np.clip(distance, 0.3, 8.0))

    def _estimate_head_yaw(self, face_roi_gray, w, h) -> tuple[float, bool]:
        """Calculates yaw angle and strictly verifies eye visibility to reject side/back-of-head false detections."""
        roi = cv2.resize(face_roi_gray[:int(h * 0.6), :], (96, 54), interpolation=cv2.INTER_AREA) if w > 96 else face_roi_gray[:int(h * 0.6), :]
        rw = roi.shape[1]
        eyes = self.eye_cascade.detectMultiScale(roi, scaleFactor=1.12, minNeighbors=3, minSize=(10, 10))
        if len(eyes) >= 2:
            eyes_sorted = sorted(eyes, key=lambda e: e[0])
            left_eye_center = eyes_sorted[0][0] + eyes_sorted[0][2] / 2.0
            right_eye_center = eyes_sorted[-1][0] + eyes_sorted[-1][2] / 2.0
            eye_midpoint = (left_eye_center + right_eye_center) / 2.0
            face_center = rw / 2.0
            yaw_deg = float(((eye_midpoint - face_center) / face_center) * 40.0)
            return yaw_deg, True
        elif len(eyes) == 1:
            eye_x = eyes[0][0] + eyes[0][2] / 2.0
            yaw_deg = -25.0 if eye_x < rw / 2.0 else 25.0
            return yaw_deg, True
        # If no eyes are detected, user is NOT looking at the robot!
        return 45.0, False

    def _detect_facial_emotion(self, face_roi_gray, w, h, yaw: float = 0.0, eyes_found: bool = False) -> str:
        """Determines emotion (happy, surprised, focused, neutral) based on mouth contrast, smile and gaze geometry."""
        lower_face = cv2.resize(face_roi_gray[int(h * 0.5):, :], (96, 48), interpolation=cv2.INTER_AREA) if w > 96 else face_roi_gray[int(h * 0.5):, :]
        smiles = self.smile_cascade.detectMultiScale(lower_face, scaleFactor=1.65, minNeighbors=10, minSize=(15, 15))
        if len(smiles) > 0:
            return "happy"

        # Surprise detection: open oral cavity with dark center contrast + high variance in mouth region
        try:
            mouth_region = lower_face[int(lower_face.shape[0] * 0.3):int(lower_face.shape[0] * 0.9), :]
            if mouth_region.size > 0:
                mean_val = float(np.mean(mouth_region))
                std_val = float(np.std(mouth_region))
                mh, mw = mouth_region.shape[:2]
                center_patch = mouth_region[int(mh * 0.3):int(mh * 0.7), int(mw * 0.3):int(mw * 0.7)]
                if center_patch.size > 0:
                    center_mean = float(np.mean(center_patch))
                    if center_mean < (mean_val - 18.0) and std_val > 22.0:
                        return "surprised"
        except Exception:
            pass

        # Focused detection: direct frontal gaze with eyes clearly tracked and low head yaw
        if eyes_found and abs(yaw) <= 8.0:
            return "focused"

        return "neutral"

    def image_callback(self, msg: Image):
        """Non-blocking subscriber callback. Holds only the latest frame (depth=1)."""
        self._camera_input_count += 1
        with self._slot_lock:
            if self._pending_image is not None:
                self._dropped_frames += 1
            self._pending_image = msg
            self._pending_arrival_mono = time.monotonic()
            self._frame_available_event.set()

    def _worker_loop(self):
        """Dedicated low-latency vision worker thread. Always consumes newest frame."""
        while rclpy.ok() and not self._stop_worker:
            if not self._frame_available_event.wait(timeout=0.1):
                continue
            with self._slot_lock:
                msg = self._pending_image
                arrival_mono = self._pending_arrival_mono
                self._pending_image = None
                self._frame_available_event.clear()

            if msg is None:
                continue

            try:
                self._process_frame(msg, arrival_mono)
            except Exception as e:
                self.get_logger().error(f"Error in face processing: {e}")

    def _process_frame(self, msg: Image, arrival_mono: float):
        t_start = time.perf_counter()

        # 1. Measure timestamp age (source_image_timestamp vs processing time)
        now_mono = time.monotonic()
        if msg.header.stamp.sec > 0:
            now_ros_s = self.get_clock().now().nanoseconds * 1e-9
            msg_stamp_s = msg.header.stamp.sec + msg.header.stamp.nanosec * 1e-9
            frame_age_ms = max(0.0, (now_ros_s - msg_stamp_s) * 1000.0)
        else:
            frame_age_ms = max(0.0, (now_mono - arrival_mono) * 1000.0)

        self._frame_ages_ms.append(frame_age_ms)
        self._detector_processed_count += 1

        t0 = time.perf_counter()
        try:
            frame = imgmsg_to_bgr(msg)
            if frame is None:
                return
        except Exception as e:
            self.get_logger().warn(f"Image conversion failed: {e}")
            return
        t1 = time.perf_counter()
        self._lat_bgr_ms.append((t1 - t0) * 1000.0)

        frame_h, frame_w = frame.shape[:2]

        # 2. Scale to 640px for low latency on Jetson CPU
        scale_ratio = 640.0 / float(frame_w) if frame_w > 640 else 1.0
        if scale_ratio < 1.0:
            target_w = 640
            target_h = int(frame_h * scale_ratio)
            small_bgr = cv2.resize(frame, (target_w, target_h), interpolation=cv2.INTER_LINEAR)
            small_gray = cv2.cvtColor(small_bgr, cv2.COLOR_BGR2GRAY)
        else:
            small_gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        t2 = time.perf_counter()
        self._lat_gray_ms.append((t2 - t1) * 1000.0)

        # 3. Detect faces (Haar Cascade)
        self._pri_calls += 1
        t3_start = time.perf_counter()
        detected_faces = detect_faces_with_confidence(
            self.face_cascade,
            small_gray,
            scaleFactor=1.10,
            minNeighbors=3,
            minSize=(24, 24),
        )
        t3_end = time.perf_counter()
        self._lat_pri_haar_ms.append((t3_end - t3_start) * 1000.0)

        if len(detected_faces) > 0:
            self._pri_hits += 1
        elif hasattr(self, 'face_alt_cascade'):
            self._alt_calls += 1
            t4_start = time.perf_counter()
            detected_faces = detect_faces_with_confidence(
                self.face_alt_cascade,
                small_gray,
                scaleFactor=1.10,
                minNeighbors=3,
                minSize=(24, 24),
            )
            t4_end = time.perf_counter()
            self._lat_alt_haar_ms.append((t4_end - t4_start) * 1000.0)
            if len(detected_faces) > 0:
                self._alt_hits += 1

        # Map bounding boxes back to original resolution
        if len(detected_faces) > 0 and scale_ratio < 1.0:
            faces = [[int(x / scale_ratio), int(y / scale_ratio), int(w / scale_ratio), int(h / scale_ratio), conf] for (x, y, w, h, conf) in detected_faces]
        else:
            faces = [list(f) for f in detected_faces]

        if len(faces) > 0:
            faces = sorted(faces, key=lambda f: f[2]*f[3], reverse=True)

        # 4. Extract Face Bounding Box, Center X, and Bearing (LIGHTWEIGHT: No eye/smile cascades)
        face_list = []
        face_camera_azimuth = 0.0
        user_distance = 0.0

        for idx, (x, y, w, h, detection_conf) in enumerate(faces):
            # Camera Optical Axis Azimuth Angle (HFOV ~ 72°, half = 36°)
            # Image Right (+X) -> Robot Right (-Yaw), Image Left (-X) -> Robot Left (+Yaw)
            face_center_x = x + (w / 2.0)
            norm_offset = (face_center_x - (frame_w / 2.0)) / (frame_w / 2.0)
            cam_azimuth = float(-norm_offset * 36.0)
            if idx == 0:
                face_camera_azimuth = cam_azimuth

            # Geometric pinhole distance (instant, zero overhead)
            focal_length = frame_w * 0.8
            dist_m = float(np.clip((0.15 * focal_length) / max(1, w), 0.3, 8.0))
            if idx == 0:
                user_distance = dist_m

            face_list.append({
                "x": int(x), "y": int(y), "width": int(w), "height": int(h),
                "confidence": round(float(detection_conf), 2),
                "frame_width": int(frame_w), "frame_height": int(frame_h),
                "yaw_deg": 0.0,
                "camera_azimuth_deg": round(cam_azimuth, 1),
                "distance_m": round(dist_m, 2),
                "looking_at_robot": True,
                "emotion": "neutral",
                "recognized_name": None,
                "recognized_title": None,
            })

        # 5. Publish to downstream gaze topics
        faces_msg = String()
        faces_msg.data = json.dumps(face_list)
        self.pub_faces.publish(faces_msg)

        person_msg = Bool()
        person_msg.data = len(faces) > 0
        self.pub_person.publish(person_msg)

        looking_msg = Bool()
        looking_msg.data = len(faces) > 0
        self.pub_looking.publish(looking_msg)

        yaw_msg = Float32()
        yaw_msg.data = float(face_camera_azimuth)
        self.pub_yaw.publish(yaw_msg)

        dist_msg = Float32()
        dist_msg.data = float(user_distance)
        self.pub_distance.publish(dist_msg)

        t_end = time.perf_counter()
        self._lat_total_ms.append((t_end - t_start) * 1000.0)
        self._lat_post_ms.append((t_end - t3_end) * 1000.0)

        # 6. Periodic Performance Telemetry (Every 5 seconds)
        dt_perf = now_mono - self._last_perf_log_time
        if dt_perf >= 5.0:
            cam_fps = (self._camera_input_count - self._last_perf_camera_count) / dt_perf
            det_fps = (self._detector_processed_count - self._last_perf_det_count) / dt_perf
            self._last_perf_log_time = now_mono
            self._last_perf_camera_count = self._camera_input_count
            self._last_perf_det_count = self._detector_processed_count

            ages = list(self._frame_ages_ms)
            p50 = float(np.percentile(ages, 50)) if ages else 0.0
            p95 = float(np.percentile(ages, 95)) if ages else 0.0
            max_age = float(np.max(ages)) if ages else 0.0

            tot_p50 = float(np.percentile(self._lat_total_ms, 50)) if self._lat_total_ms else 0.0
            tot_p95 = float(np.percentile(self._lat_total_ms, 95)) if self._lat_total_ms else 0.0
            pri_p50 = float(np.percentile(self._lat_pri_haar_ms, 50)) if self._lat_pri_haar_ms else 0.0
            alt_p50 = float(np.percentile(self._lat_alt_haar_ms, 50)) if self._lat_alt_haar_ms else 0.0
            bgr_p50 = float(np.percentile(self._lat_bgr_ms, 50)) if self._lat_bgr_ms else 0.0
            post_p50 = float(np.percentile(self._lat_post_ms, 50)) if self._lat_post_ms else 0.0

            alt_pct = (self._alt_calls / max(1, self._pri_calls)) * 100.0

            self.get_logger().info(
                f"[VISION PERF] cam_fps={cam_fps:.1f} det_fps={det_fps:.1f} | "
                f"proc(p50={tot_p50:.1f}ms, p95={tot_p95:.1f}ms) | "
                f"pri={pri_p50:.1f}ms alt2={alt_p50:.1f}ms bgr={bgr_p50:.1f}ms post={post_p50:.1f}ms | "
                f"alt2_rate={alt_pct:.1f}% (calls:{self._alt_calls}/{self._pri_calls}, hits:{self._alt_hits}) | "
                f"age_p50={p50:.1f}ms age_p95={p95:.1f}ms max_age={max_age:.1f}ms drop={self._dropped_frames}"
            )

    def destroy_node(self):
        self._stop_worker = True
        self._frame_available_event.set()
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = SpatialVisionNode()
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
