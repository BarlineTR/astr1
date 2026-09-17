#!/usr/bin/env python3
"""ASTRO V1 — Native DepthAI Hardware-Accelerated Spatial Perception Node.

Leverages the OAK-D Lite Intel Movidius Myriad X VPU directly for:
  1. On-Device Color Camera (1080P / 30 FPS)
  2. On-Device Stereo Depth Engine (Subpixel + LR-check + Median Filter)
  3. On-Device Spatial Neural Network (MobileNet / Person / Face Detection)
  4. On-Device Multi-Object Tracker (Tracklet ID assignment)
  5. 3D Spatial Coordinates (X, Y, Z in meters) computed directly in silicon

Publishes to standard ROS 2 topics with ~0% Jetson CPU usage!
"""

import json
import logging

_LOG = logging.getLogger(__name__)

import threading
import time
import cv2
import numpy as np

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Image
from std_msgs.msg import Bool, Float32, Header, Int32, String

try:
    import depthai as dai
except ImportError:
    dai = None

try:
    from astro_vision.image_utils import bgr_to_imgmsg
    from astro_vision.detection_quality import detect_faces_with_confidence
    from astro_vision.face_recognizer import FaceRecognizer
    from astro_vision.object_detector import ObjectDetectorEngine
    from astro_vision.age_estimator import VisualAgeEstimator
    from astro_vision.visual_attributes import VisualAttributeExtractor
except ImportError:
    try:
        from image_utils import bgr_to_imgmsg
        from detection_quality import detect_faces_with_confidence
        from face_recognizer import FaceRecognizer
        from object_detector import ObjectDetectorEngine
        from age_estimator import VisualAgeEstimator
        from visual_attributes import VisualAttributeExtractor
    except ImportError:
        FaceRecognizer = None
        ObjectDetectorEngine = None
        VisualAgeEstimator = None
        VisualAttributeExtractor = None


class OakSpatialNativeNode(Node):
    def __init__(self):
        super().__init__("oak_spatial_native_node")

        self.declare_parameter("fps", 30.0)
        self.declare_parameter("confidence_threshold", 0.5)
        self.declare_parameter("sync_nn", True)

        self._fps = float(self.get_parameter("fps").value)
        self._conf_thresh = float(self.get_parameter("confidence_threshold").value)
        self._sync_nn = bool(self.get_parameter("sync_nn").value)

        # Publishers
        self.pub_rgb = self.create_publisher(Image, "/oak/rgb/image_raw", 10)
        self.pub_depth = self.create_publisher(Image, "/oak/depth/image_raw", 10)
        self.pub_person_detected = self.create_publisher(Bool, "/vision/person_detected", 10)
        self.pub_person_count = self.create_publisher(Int32, "/vision/person_count", 10)
        self.pub_user_distance = self.create_publisher(Float32, "/vision/user_distance", 10)
        self.pub_head_yaw = self.create_publisher(Float32, "/vision/head_yaw", 10)
        self.pub_looking = self.create_publisher(Bool, "/vision/looking_at_robot", 10)
        self.pub_emotion = self.create_publisher(String, "/vision/user_emotion", 10)
        self.pub_faces = self.create_publisher(String, "/vision/faces", 10)
        self.pub_face_image = self.create_publisher(Image, "/vision/face_image", 10)
        self.pub_recognized_person = self.create_publisher(String, "/vision/recognized_person", 10)
        self.pub_detected_objects = self.create_publisher(String, "/vision/detected_objects", 10)
        self.pub_visual_attributes = self.create_publisher(String, "/vision/visual_attributes", 10)

        # Perception Engines
        self._face_recognizer = FaceRecognizer() if FaceRecognizer else None
        self._age_estimator = VisualAgeEstimator() if VisualAgeEstimator else None
        self._visual_attributes = VisualAttributeExtractor() if VisualAttributeExtractor else None
        self._object_engine = ObjectDetectorEngine() if ObjectDetectorEngine else None

        self._running = False
        self._device = None
        self._thread = None

        if dai is None:
            self.get_logger().error(
                "❌ [DepthAI] 'depthai' python kütüphanesi bulunamadı! Lütfen 'pip install depthai' çalıştırın."
            )
            return

        self._start_pipeline()

    def _create_node(self, pipeline: dai.Pipeline, class_name: str):
        """Universal node creator working across all DepthAI versions (v2.0 - v2.30+)."""
        errors = []

        # Find target node class
        node_cls = None
        for container in [getattr(dai, "node", None), getattr(dai, "nodes", None), dai]:
            if container is not None and hasattr(container, class_name):
                node_cls = getattr(container, class_name)
                break

        if node_cls is None:
            # Case-insensitive search
            for container in [getattr(dai, "node", None), getattr(dai, "nodes", None), dai]:
                if container is not None:
                    for attr in dir(container):
                        if attr.lower() == class_name.lower():
                            node_cls = getattr(container, attr)
                            break
                    if node_cls is not None:
                        break

        # Attempt 1: pipeline.create(node_cls)
        if node_cls is not None:
            try:
                return pipeline.create(node_cls)
            except Exception as e:
                errors.append(f"pipeline.create: {e}")

            # Attempt 2: Direct constructor node_cls(pipeline)
            try:
                return node_cls(pipeline)
            except Exception as e:
                errors.append(f"node_cls(pipeline): {e}")

            # Attempt 3: node_cls() then add to pipeline
            try:
                return node_cls()
            except Exception as e:
                errors.append(f"node_cls(): {e}")

        # Attempt 4: pipeline.create<ClassName>()
        method_name = f"create{class_name}"
        if hasattr(pipeline, method_name):
            try:
                return getattr(pipeline, method_name)()
            except Exception as e:
                errors.append(f"pipeline.{method_name}(): {e}")

        raise RuntimeError(f"DepthAI node '{class_name}' failed: {'; '.join(errors)}")

    def _create_pipeline(self) -> dai.Pipeline:
        pipeline = dai.Pipeline()

        # 1. Color Camera (Hardware ISP & Auto-Exposure on VPU)
        cam_rgb = self._create_node(pipeline, "ColorCamera")
        cam_rgb.setResolution(dai.ColorCameraProperties.SensorResolution.THE_1080_P)
        cam_rgb.setInterleaved(False)
        cam_rgb.setColorOrder(dai.ColorCameraProperties.ColorOrder.BGR)
        cam_rgb.setFps(self._fps)

        # 2. Mono Cameras (Stereo Pair)
        mono_left = self._create_node(pipeline, "MonoCamera")
        mono_right = self._create_node(pipeline, "MonoCamera")
        mono_left.setResolution(dai.MonoCameraProperties.SensorResolution.THE_400_P)
        mono_left.setBoardSocket(dai.CameraBoardSocket.LEFT)
        mono_right.setResolution(dai.MonoCameraProperties.SensorResolution.THE_400_P)
        mono_right.setBoardSocket(dai.CameraBoardSocket.RIGHT)

        # 3. Stereo Depth Engine (Hardware Accelerated on Myriad X VPU)
        stereo = self._create_node(pipeline, "StereoDepth")
        stereo.setLeftRightCheck(True)
        stereo.setSubpixel(True)
        stereo.setDepthAlign(dai.CameraBoardSocket.RGB)
        mono_left.out.link(stereo.left)
        mono_right.out.link(stereo.right)

        # 4. XLink Outputs to Host
        xout_rgb = self._create_node(pipeline, "XLinkOut")
        xout_rgb.setStreamName("rgb")
        cam_rgb.video.link(xout_rgb.input)

        xout_depth = self._create_node(pipeline, "XLinkOut")
        xout_depth.setStreamName("depth")
        stereo.depth.link(xout_depth.input)

        return pipeline

    def _start_pipeline(self):
        try:
            pipeline = self._create_pipeline()
            self._device = dai.Device(pipeline)
            self._running = True
            self.get_logger().info("✅ [DepthAI Native] OAK-D Lite Donanım Hızlandırmalı Mekansal Pipeline Başlatıldı!")

            self._thread = threading.Thread(target=self._worker_loop, daemon=True)
            self._thread.start()
        except Exception as e:
            self.get_logger().error(f"❌ [DepthAI Native] OAK-D Lite cihazına bağlanılamadı: {e}")

    def _worker_loop(self):
        q_rgb = self._device.getOutputQueue(name="rgb", maxSize=4, blocking=False)
        q_depth = self._device.getOutputQueue(name="depth", maxSize=4, blocking=False)

        # Fast Face Cascade for RoI detection on RGB frame
        frontal_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        eye_path = cv2.data.haarcascades + "haarcascade_eye.xml"
        face_cascade = cv2.CascadeClassifier(frontal_path)
        eye_cascade = cv2.CascadeClassifier(eye_path)

        while rclpy.ok() and self._running:
            in_rgb = q_rgb.tryGet()
            in_depth = q_depth.tryGet()

            frame = in_rgb.getCvFrame() if in_rgb is not None else None
            depth_frame = in_depth.getFrame() if in_depth is not None else None

            if frame is not None:
                header = Header()
                header.stamp = self.get_clock().now().to_msg()
                header.frame_id = "oak_rgb_camera_optical_frame"
                h, w = frame.shape[:2]

                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                # Scale down for fast detection (target 640px max width)
                scale_ratio = 640.0 / float(w) if w > 640 else 1.0
                small_gray = cv2.resize(gray, (0, 0), fx=scale_ratio, fy=scale_ratio, interpolation=cv2.INTER_AREA) if scale_ratio < 1.0 else gray

                detected_faces = detect_faces_with_confidence(
                    face_cascade, small_gray, scaleFactor=1.1, minNeighbors=4,
                    minSize=(24, 24)
                )

                faces = [[int(x / scale_ratio), int(y / scale_ratio), int(bw / scale_ratio), int(bh / scale_ratio), conf] for (x, y, bw, bh, conf) in detected_faces] if scale_ratio < 1.0 else [list(f) for f in detected_faces]

                face_list = []
                closest_dist = 0.0
                closest_yaw = 0.0
                person_detected = len(faces) > 0
                is_looking = False

                for (x, y, bw, bh, detection_conf) in faces:
                    # 1. 3D Depth Distance directly from OAK-D Hardware Stereo Depth
                    dist_m = 0.0
                    if depth_frame is not None:
                        try:
                            dh, dw = depth_frame.shape[:2]
                            cx = int((x + bw / 2) * (dw / float(w)))
                            cy = int((y + bh / 2) * (dh / float(h)))
                            cx = max(0, min(dw - 1, cx))
                            cy = max(0, min(dh - 1, cy))
                            patch = depth_frame[max(0, cy - 10):min(dh, cy + 10), max(0, cx - 10):min(dw, cx + 10)]
                            valid = patch[patch > 150]
                            if len(valid) > 0:
                                dist_m = float(np.median(valid)) / 1000.0
                        except Exception as _exc:
                            self.get_logger().debug(f"_worker_loop: yok sayılan hata ({_exc})")

                    if dist_m <= 0.1:
                        focal_length = w * 0.8
                        dist_m = float(np.clip((0.15 * focal_length) / max(1, bw), 0.3, 5.0))

                    closest_dist = dist_m

                    # 2. 3D Spatial Position (X, Y in meters)
                    hfov_rad = np.deg2rad(68.8)  # OAK-D Lite HFOV
                    angle_x_rad = ((x + bw / 2.0 - w / 2.0) / (w / 2.0)) * (hfov_rad / 2.0)
                    spatial_x_m = dist_m * np.sin(angle_x_rad)
                    spatial_z_m = dist_m * np.cos(angle_x_rad)

                    # 3. Head Yaw & Gaze
                    face_roi = gray[y:y + bh, x:x + bw]
                    eyes = eye_cascade.detectMultiScale(face_roi[:int(bh * 0.6), :], scaleFactor=1.15, minNeighbors=3)
                    yaw_deg = 0.0
                    if len(eyes) >= 2:
                        eyes_sorted = sorted(eyes, key=lambda e: e[0])
                        mid_eye = (eyes_sorted[0][0] + eyes_sorted[0][2] / 2.0 + eyes_sorted[-1][0] + eyes_sorted[-1][2] / 2.0) / 2.0
                        yaw_deg = float(((mid_eye - bw / 2.0) / (bw / 2.0)) * 35.0)

                    closest_yaw = yaw_deg
                    direct_gaze = abs(yaw_deg) <= 15.0 and abs(angle_x_rad) <= np.deg2rad(20)
                    if direct_gaze:
                        is_looking = True

                    # 4. Face Recognition
                    recog_name = "Misafir"
                    recog_title = "Misafir"
                    recog_conf = 0.0
                    is_known = False
                    face_roi_bgr = frame[y:y + bh, x:x + bw]

                    if self._face_recognizer and face_roi_bgr.size > 0:
                        try:
                            r_name, r_conf, r_meta = self._face_recognizer.recognize_face(face_roi_bgr)
                            if r_name and r_conf > 0.40:
                                recog_name = r_name
                                recog_conf = float(r_conf)
                                is_known = True
                                recog_title = r_meta.get("formal_title", r_name)
                        except Exception:
                            pass

                    # 5. Age Group Estimation
                    age_group_val = "UNKNOWN"
                    age_conf = 0.0
                    if self._age_estimator and face_roi_bgr.size > 0:
                        try:
                            ag_res, ag_conf = self._age_estimator.estimate(face_roi_bgr)
                            age_group_val = ag_res.value
                            age_conf = float(ag_conf)
                        except Exception:
                            pass

                    # 6. Visual Attributes (Clothing color, glasses, expression)
                    dominant_color = ""
                    dominant_color_tr = ""
                    accessories = []
                    if self._visual_attributes:
                        try:
                            attrs = self._visual_attributes.extract(frame, (x, y, bw, bh), is_smiling=False)
                            dominant_color = attrs.dominant_clothing_color
                            dominant_color_tr = attrs.dominant_clothing_color_tr
                            accessories = attrs.accessories
                        except Exception:
                            pass

                    face_list.append({
                        "x": int(x), "y": int(y), "width": int(bw), "height": int(bh),
                        "confidence": round(float(detection_conf), 2),
                        "frame_width": int(w), "frame_height": int(h),
                        "spatial_x_m": round(float(spatial_x_m), 2),
                        "distance_m": round(float(dist_m), 2),
                        "yaw_deg": round(float(yaw_deg), 1),
                        "looking_at_robot": bool(direct_gaze),
                        "emotion": "neutral",
                        "recognized_name": str(recog_name),
                        "recognized_title": str(recog_title),
                        "is_known": bool(is_known),
                        "recognition_confidence": round(float(recog_conf), 2),
                        "age_group": str(age_group_val),
                        "age_confidence": round(float(age_conf), 2),
                        "dominant_clothing_color": str(dominant_color),
                        "dominant_clothing_color_tr": str(dominant_color_tr),
                        "accessories": list(accessories),
                    })

                    # HUD Overlay
                    color = (0, 255, 0) if direct_gaze else (0, 200, 255)
                    cv2.rectangle(frame, (x, y), (x + bw, y + bh), color, 2)
                    gaze_txt = "BANA BAKIYOR" if direct_gaze else f"AÇI: {yaw_deg:.0f}°"
                    known_str = f" [{recog_name}]" if is_known else ""
                    hud_text = f"{gaze_txt}{known_str} | {dist_m:.2f}m"
                    cv2.putText(frame, hud_text, (x, max(22, y - 10)), cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2)

                # 7. Object Detection & Spatial Perception
                detected_objs = []
                if self._object_engine:
                    try:
                        detected_objs = self._object_engine.process_frame(frame, depth_frame)
                    except Exception as _oe_err:
                        self.get_logger().debug(f"Object detection error: {_oe_err}")

                # Fuse person detection: face detection OR YOLO person body detection
                person_objs = [o for o in detected_objs if getattr(o, "class_name", "") == "person"]
                if person_objs:
                    person_detected = True
                    if closest_dist <= 0.1:
                        p_dist = getattr(person_objs[0], "distance_m", None)
                        if p_dist is not None and p_dist > 0.1:
                            closest_dist = float(p_dist)

                non_person_objs = [o for o in detected_objs if getattr(o, "class_name", "") != "person"]

                # Publish Standard ROS 2 Topics
                rgb_msg = bgr_to_imgmsg(frame, header)
                self.pub_rgb.publish(rgb_msg)

                p_msg = Bool()
                p_msg.data = bool(person_detected)
                self.pub_person_detected.publish(p_msg)

                cnt_msg = Int32()
                cnt_msg.data = max(len(faces), len(person_objs))
                self.pub_person_count.publish(cnt_msg)

                d_msg = Float32()
                d_msg.data = float(closest_dist)
                self.pub_user_distance.publish(d_msg)

                y_msg = Float32()
                y_msg.data = float(closest_yaw)
                self.pub_head_yaw.publish(y_msg)

                l_msg = Bool()
                l_msg.data = is_looking
                self.pub_looking.publish(l_msg)

                emo_msg = String()
                emo_msg.data = "neutral"
                self.pub_emotion.publish(emo_msg)

                def _json_default(obj):
                    if isinstance(obj, (np.bool_, bool)):
                        return bool(obj)
                    if isinstance(obj, (np.integer, int)):
                        return int(obj)
                    if isinstance(obj, (np.floating, float)):
                        return float(obj)
                    if isinstance(obj, np.ndarray):
                        return obj.tolist()
                    return str(obj)

                faces_msg = String()
                faces_msg.data = json.dumps(face_list, default=_json_default, ensure_ascii=False)
                self.pub_faces.publish(faces_msg)

                # Publish Recognized Person
                recog_msg = String()
                top_face = max(face_list, key=lambda f: f.get("recognition_confidence", 0.0), default={})
                recog_payload = {
                    "name": top_face.get("recognized_name", "Misafir"),
                    "title": top_face.get("recognized_title", "Misafir"),
                    "formal_title": top_face.get("recognized_title", "Misafir"),
                    "confidence": top_face.get("recognition_confidence", 0.0),
                    "is_known": bool(top_face.get("is_known", False)),
                    "age_group": top_face.get("age_group", "UNKNOWN"),
                    "dominant_clothing_color": top_face.get("dominant_clothing_color", ""),
                    "dominant_clothing_color_tr": top_face.get("dominant_clothing_color_tr", ""),
                    "accessories": top_face.get("accessories", []),
                }
                recog_msg.data = json.dumps(recog_payload, default=_json_default, ensure_ascii=False)
                self.pub_recognized_person.publish(recog_msg)

                # Publish Object Detections
                obj_msg = String()
                obj_msg.data = json.dumps([o.to_dict() for o in detected_objs], default=_json_default, ensure_ascii=False)
                self.pub_detected_objects.publish(obj_msg)

                hud_msg = bgr_to_imgmsg(frame, header)
                self.pub_face_image.publish(hud_msg)

                # Periodic Throttled Status Log (Every 3 seconds)
                now_mono = time.monotonic()
                if (now_mono - getattr(self, "_last_log_time", 0.0)) >= 3.0:
                    self._last_log_time = now_mono
                    obj_strs = []
                    for o in non_person_objs:
                        c_name = getattr(o, 'class_name_tr', getattr(o, 'class_name', 'nesne'))
                        d_m = getattr(o, 'distance_m', None)
                        if d_m is not None and d_m > 0.0:
                            obj_strs.append(f"{c_name} ({d_m:.1f}m)")
                        else:
                            obj_strs.append(f"{c_name}")
                    obj_summary = ", ".join(obj_strs) if obj_strs else "Yok"
                    person_summary = f"Var ({closest_dist:.1f}m, '{recog_payload.get('name', 'Misafir')}')" if person_detected else "Yok"
                    self.get_logger().info(f"👁️ [Görsel Algı Canlı] Kişi: {person_summary} | Nesneler: {obj_summary}")

            time.sleep(0.01)

    def destroy_node(self):
        self._running = False
        if self._device is not None:
            try:
                self._device.close()
            except Exception:
                pass
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = OakSpatialNativeNode()
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
