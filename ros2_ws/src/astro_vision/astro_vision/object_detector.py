"""ASTRO V1 — Real Object Detection & Spatial Perception Engine.

Supports lightweight COCO 80 object detection (OpenCV DNN / ONNX / DepthAI),
3D spatial localization via stereo depth correlation, multi-frame object tracking,
and deterministic fixture backends for verification.
"""

from dataclasses import dataclass, field
import json
import math
import os
import time
from typing import Any, Dict, List, Optional, Set, Tuple

import numpy as np

# Standard 80 COCO Classes
COCO_CLASSES: Tuple[str, ...] = (
    "person", "bicycle", "car", "motorcycle", "airplane", "bus", "train", "truck", "boat", "traffic light",
    "fire hydrant", "stop sign", "parking meter", "bench", "bird", "cat", "dog", "horse", "sheep", "cow",
    "elephant", "bear", "zebra", "giraffe", "backpack", "umbrella", "handbag", "tie", "suitcase", "frisbee",
    "skis", "snowboard", "sports ball", "kite", "baseball bat", "baseball glove", "skateboard", "surfboard",
    "tennis racket", "bottle", "wine glass", "cup", "fork", "knife", "spoon", "bowl", "banana", "apple",
    "sandwich", "orange", "broccoli", "carrot", "hot dog", "pizza", "donut", "cake", "chair", "couch",
    "potted plant", "bed", "dining table", "toilet", "tv", "laptop", "mouse", "remote", "keyboard", "cell phone",
    "microwave", "oven", "toaster", "sink", "refrigerator", "book", "clock", "vase", "scissors", "teddy bear",
    "hair drier", "toothbrush"
)

# Priority Classes for ASTRO Domestic Social Perception
PRIORITY_CLASSES: Set[str] = {
    "cup", "bottle", "cell phone", "laptop", "book", "backpack", "handbag", "suitcase",
    "bowl", "fork", "knife", "spoon", "remote", "banana", "apple", "sandwich", "orange",
    "broccoli", "carrot", "hot dog", "pizza", "donut", "cake", "chair", "keyboard", "mouse"
}

# Natural Turkish Translations
CLASS_TRANSLATIONS_TR: Dict[str, str] = {
    "cup": "bardak",
    "bottle": "su şişesi",
    "cell phone": "telefon",
    "laptop": "dizüstü bilgisayar",
    "book": "kitap",
    "backpack": "sırt çantası",
    "handbag": "çanta",
    "suitcase": "valiz",
    "remote": "kumanda",
    "bowl": "kase",
    "fork": "çatal",
    "knife": "bıçak",
    "spoon": "kaşık",
    "chair": "sandalye",
    "couch": "koltuk",
    "keyboard": "klavye",
    "mouse": "fare",
    "person": "kişi",
    "banana": "muz",
    "apple": "elma",
    "sandwich": "sandviç",
    "orange": "portakal",
    "pizza": "pizza",
    "cake": "kek",
}

# Abstract / Non-Standard Categories that must NOT be hallucinated
UNSUPPORTED_ABSTRACT_CLASSES: Set[str] = {
    "food",   # Generic abstract food (only specific edibles like apple/sandwich exist in COCO)
    "plate",  # Plate is in LVIS/OpenImages, NOT in standard COCO 80 (only bowl exists)
    "tea",    # Abstract beverage/liquid (detector only detects container like cup/bottle)
    "coffee", # Abstract beverage/liquid (detector only detects container like cup/bottle)
}


@dataclass
class DetectedObject:
    """Represents an object detected in a single video frame."""

    object_id: str
    class_name: str
    confidence: float
    bbox: Tuple[int, int, int, int]  # (xmin, ymin, xmax, ymax)
    center: Tuple[float, float]      # (cx, cy) in image pixels
    distance_m: Optional[float] = None
    spatial_coords: Optional[Tuple[float, float, float]] = None  # (x, y, z) in meters
    timestamp: float = field(default_factory=time.time)
    source: str = "oak_rgb"
    is_supported: bool = True

    @property
    def class_name_tr(self) -> str:
        return CLASS_TRANSLATIONS_TR.get(self.class_name, self.class_name)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "object_id": self.object_id,
            "class_name": self.class_name,
            "class_name_tr": self.class_name_tr,
            "confidence": round(float(self.confidence), 3),
            "bbox": [int(v) for v in self.bbox],
            "center": [round(float(v), 1) for v in self.center],
            "distance_m": round(float(self.distance_m), 2) if self.distance_m is not None else None,
            "spatial_coords": [round(float(v), 2) for v in self.spatial_coords] if self.spatial_coords is not None else None,
            "timestamp": self.timestamp,
            "source": self.source,
            "is_supported": self.is_supported,
        }


class BaseObjectDetector:
    """Base interface for object detection implementations."""

    def detect(
        self,
        image_bgr: np.ndarray,
        depth_map: Optional[np.ndarray] = None,
        min_confidence: float = 0.50,
    ) -> List[DetectedObject]:
        raise NotImplementedError


class SyntheticObjectDetector(BaseObjectDetector):
    """Deterministic fixture detector for offline verification, CI, and test suites."""

    def __init__(self):
        self._preset_detections: List[DetectedObject] = []

    def set_preset_detections(self, detections: List[DetectedObject]) -> None:
        self._preset_detections = list(detections)

    def inject_detection(
        self,
        class_name: str,
        confidence: float = 0.90,
        bbox: Tuple[int, int, int, int] = (100, 100, 200, 200),
        distance_m: Optional[float] = 1.0,
        object_id: Optional[str] = None,
    ) -> DetectedObject:
        cx = (bbox[0] + bbox[2]) / 2.0
        cy = (bbox[1] + bbox[3]) / 2.0
        oid = object_id or f"{class_name}_{len(self._preset_detections)}"
        det = DetectedObject(
            object_id=oid,
            class_name=class_name,
            confidence=confidence,
            bbox=tuple(bbox),
            center=(cx, cy),
            distance_m=distance_m,
            spatial_coords=(0.0, 0.0, distance_m) if distance_m else None,
            timestamp=time.time(),
        )
        self._preset_detections.append(det)
        return det

    def clear(self) -> None:
        self._preset_detections.clear()

    def detect(
        self,
        image_bgr: np.ndarray,
        depth_map: Optional[np.ndarray] = None,
        min_confidence: float = 0.50,
    ) -> List[DetectedObject]:
        now = time.time()
        results = []
        for det in self._preset_detections:
            if det.confidence >= min_confidence:
                # Update timestamp to current execution time
                d = DetectedObject(
                    object_id=det.object_id,
                    class_name=det.class_name,
                    confidence=det.confidence,
                    bbox=det.bbox,
                    center=det.center,
                    distance_m=det.distance_m,
                    spatial_coords=det.spatial_coords,
                    timestamp=now,
                    source=det.source,
                    is_supported=det.is_supported,
                )
                results.append(d)
        return results


class OpenCvDnnObjectDetector(BaseObjectDetector):
    """OpenCV DNN inference backend for YOLO / MobileNet ONNX models.

    Runs on host Jetson (CPU or CUDA) or developer workstation without requiring PyTorch.
    """

    def __init__(
        self,
        model_path: Optional[str] = None,
        input_size: Tuple[int, int] = (640, 640),
        confidence_threshold: float = 0.50,
        nms_threshold: float = 0.45,
    ):
        self.input_size = input_size
        self.confidence_threshold = confidence_threshold
        self.nms_threshold = nms_threshold
        self._net = None
        self._is_ready = False

        if model_path and os.path.exists(model_path):
            try:
                import cv2
                self._net = cv2.dnn.readNet(model_path)
                # Attempt to use CUDA if available, fallback to CPU
                try:
                    self._net.setPreferableBackend(cv2.dnn.DNN_BACKEND_CUDA)
                    self._net.setPreferableTarget(cv2.dnn.DNN_TARGET_CUDA)
                except Exception:
                    self._net.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV)
                    self._net.setPreferableTarget(cv2.dnn.DNN_TARGET_CPU)
                self._is_ready = True
            except Exception as e:
                self._is_ready = False

    @property
    def is_ready(self) -> bool:
        return self._is_ready

    def detect(
        self,
        image_bgr: np.ndarray,
        depth_map: Optional[np.ndarray] = None,
        min_confidence: float = 0.50,
    ) -> List[DetectedObject]:
        if not self._is_ready or self._net is None or image_bgr is None:
            return []

        import cv2

        h, w = image_bgr.shape[:2]
        blob = cv2.dnn.blobFromImage(
            image_bgr, 1.0 / 255.0, self.input_size, [0, 0, 0], swapRB=True, crop=False
        )
        self._net.setInput(blob)
        outputs = self._net.forward()

        # Handle YOLOv8 / standard detection tensor format
        detections: List[DetectedObject] = []
        conf_thresh = max(self.confidence_threshold, min_confidence)

        # Standard YOLOv8 output shape is [1, 84, 8400] (cx, cy, w, h, 80 class probs)
        if len(outputs.shape) == 3 and outputs.shape[1] == 84:
            predictions = outputs[0].transpose()  # [8400, 84]
            boxes, confidences, class_ids = [], [], []

            x_factor = w / float(self.input_size[0])
            y_factor = h / float(self.input_size[1])

            for row in predictions:
                classes_scores = row[4:]
                class_id = int(np.argmax(classes_scores))
                score = float(classes_scores[class_id])

                if score >= conf_thresh:
                    cx, cy, bw, bh = row[0], row[1], row[2], row[3]
                    left = int((cx - 0.5 * bw) * x_factor)
                    top = int((cy - 0.5 * bh) * y_factor)
                    width = int(bw * x_factor)
                    height = int(bh * y_factor)

                    boxes.append([left, top, width, height])
                    confidences.append(score)
                    class_ids.append(class_id)

            indices = cv2.dnn.NMSBoxes(boxes, confidences, conf_thresh, self.nms_threshold)
            now = time.time()

            for i in indices:
                idx = int(i if isinstance(i, (int, np.integer)) else i[0])
                bx, by, bw, bh = boxes[idx]
                xmin = max(0, bx)
                ymin = max(0, by)
                xmax = min(w, bx + bw)
                ymax = min(h, by + bh)

                cid = class_ids[idx]
                cname = COCO_CLASSES[cid] if 0 <= cid < len(COCO_CLASSES) else f"class_{cid}"
                center_x = (xmin + xmax) / 2.0
                center_y = (ymin + ymax) / 2.0

                # Calculate spatial distance from depth map if available
                dist_m = None
                spatial_coords = None
                if depth_map is not None:
                    dist_m = self._calculate_depth(depth_map, xmin, ymin, xmax, ymax)
                    if dist_m is not None:
                        spatial_coords = self._pixel_to_camera_coords(center_x, center_y, dist_m, w, h)

                det = DetectedObject(
                    object_id=f"{cname}_{idx}",
                    class_name=cname,
                    confidence=confidences[idx],
                    bbox=(xmin, ymin, xmax, ymax),
                    center=(center_x, center_y),
                    distance_m=dist_m,
                    spatial_coords=spatial_coords,
                    timestamp=now,
                )
                detections.append(det)

        return detections

    def _calculate_depth(self, depth_map: np.ndarray, xmin: int, ymin: int, xmax: int, ymax: int) -> Optional[float]:
        """Samples median depth from the central 50% region of the bounding box."""
        cw = max(2, int((xmax - xmin) * 0.5))
        ch = max(2, int((ymax - ymin) * 0.5))
        cx = int((xmin + xmax) / 2)
        cy = int((ymin + ymax) / 2)

        x1 = max(0, cx - cw // 2)
        x2 = min(depth_map.shape[1], cx + cw // 2)
        y1 = max(0, cy - ch // 2)
        y2 = min(depth_map.shape[0], cy + ch // 2)

        roi = depth_map[y1:y2, x1:x2]
        valid = roi[roi > 100]  # Valid stereo depths (mm)
        if len(valid) == 0:
            return None
        median_mm = float(np.median(valid))
        return round(median_mm / 1000.0, 2)  # Convert mm to meters

    def _pixel_to_camera_coords(
        self, u: float, v: float, depth_m: float, img_w: int, img_h: int
    ) -> Tuple[float, float, float]:
        """Pinhole camera projection from (u, v, z) to (X, Y, Z) in camera frame."""
        # OAK-D Wide RGB typical FOV ~69 deg H, ~54 deg V
        fx = img_w / (2.0 * math.tan(math.radians(69.0 / 2.0)))
        fy = img_h / (2.0 * math.tan(math.radians(54.0 / 2.0)))
        cx = img_w / 2.0
        cy = img_h / 2.0

        x = (u - cx) * depth_m / fx
        y = (v - cy) * depth_m / fy
        z = depth_m
        return (round(x, 2), round(y, 2), round(z, 2))


class ObjectDetectorEngine:
    """High-level tracker and rate-limited manager for object detection."""

    def __init__(
        self,
        detector: Optional[BaseObjectDetector] = None,
        model_path: Optional[str] = None,
        max_rate_hz: float = 10.0,
        temporal_track_ttl_s: float = 3.0,
    ):
        if detector is not None:
            self.detector = detector
        else:
            m_path = model_path or os.environ.get("ASTRO_YOLO_MODEL", os.path.expanduser("~/.astro/models/yolov8n.onnx"))
            self.detector = OpenCvDnnObjectDetector(model_path=m_path)

        self.max_rate_hz = max_rate_hz
        self.min_interval_s = 1.0 / max_rate_hz
        self.track_ttl_s = temporal_track_ttl_s
        self._last_inference_ts: float = 0.0
        self._tracked_objects: Dict[str, DetectedObject] = {}
        self._next_track_id: int = 1

    @property
    def is_ready(self) -> bool:
        if hasattr(self.detector, "is_ready"):
            return bool(self.detector.is_ready)
        return True

    @property
    def status(self) -> str:
        if hasattr(self.detector, "is_ready"):
            return "READY" if self.detector.is_ready else "MODEL_NOT_AVAILABLE / HARDWARE_NOT_VERIFIED"
        if isinstance(self.detector, SyntheticObjectDetector):
            return "SYNTHETIC_FIXTURE_ONLY"
        return "UNKNOWN"

    def process_frame(
        self,
        image_bgr: np.ndarray,
        depth_map: Optional[np.ndarray] = None,
        min_confidence: float = 0.50,
        now: Optional[float] = None,
    ) -> List[DetectedObject]:
        t = now if now is not None else time.time()

        # Decimation / Rate-limiting guard
        if (t - self._last_inference_ts) < self.min_interval_s and self._tracked_objects:
            return self.get_active_objects(max_age_s=self.track_ttl_s, now=t)

        self._last_inference_ts = t
        raw_detections = self.detector.detect(image_bgr, depth_map, min_confidence=min_confidence)

        # Multi-frame tracking association (Centroid / Class Proximity)
        updated_tracks: Dict[str, DetectedObject] = {}
        unmatched_detections = list(raw_detections)

        for track_id, tracked in list(self._tracked_objects.items()):
            best_match_idx = -1
            best_dist = float("inf")

            for idx, det in enumerate(unmatched_detections):
                if det.class_name == tracked.class_name:
                    # Euclidean distance in normalized image plane
                    dx = det.center[0] - tracked.center[0]
                    dy = det.center[1] - tracked.center[1]
                    dist = math.hypot(dx, dy)
                    if dist < 120.0 and dist < best_dist:  # Max 120px movement between frames
                        best_dist = dist
                        best_match_idx = idx

            if best_match_idx >= 0:
                matched_det = unmatched_detections.pop(best_match_idx)
                # Keep persistent track ID
                matched_det.object_id = track_id
                updated_tracks[track_id] = matched_det
            elif (t - tracked.timestamp) < self.track_ttl_s:
                # Retain momentarily occluded object
                updated_tracks[track_id] = tracked

        # Assign new persistent IDs to remaining unmatched detections
        for det in unmatched_detections:
            new_id = f"obj_{self._next_track_id:03d}_{det.class_name}"
            self._next_track_id += 1
            det.object_id = new_id
            updated_tracks[new_id] = det

        self._tracked_objects = updated_tracks
        return list(self._tracked_objects.values())

    def get_active_objects(self, max_age_s: float = 2.5, now: Optional[float] = None) -> List[DetectedObject]:
        t = now if now is not None else time.time()
        return [
            obj for obj in self._tracked_objects.values()
            if (t - obj.timestamp) <= max_age_s
        ]

    def to_json(self, max_age_s: float = 2.5) -> str:
        active = self.get_active_objects(max_age_s=max_age_s)
        return json.dumps([obj.to_dict() for obj in active], ensure_ascii=False)
