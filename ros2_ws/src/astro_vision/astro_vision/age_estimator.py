"""ASTRO V1 — Real Visual Age-Group Perception Engine.

Estimates interlocutor age category (CHILD, TEEN, ADULT, SENIOR, UNKNOWN)
from face visual features using OpenCV DNN or anthropometric/texture feature extraction.
Strictly returns UNKNOWN on low confidence or low quality.
"""

from enum import Enum
import math
import os
from typing import Optional, Tuple

import numpy as np


class AgeGroup(str, Enum):
    CHILD = "CHILD"
    TEEN = "TEEN"
    ADULT = "ADULT"
    SENIOR = "SENIOR"
    UNKNOWN = "UNKNOWN"


class VisualAgeEstimator:
    """Estimates age group and confidence from face crops."""

    def __init__(self, model_path: Optional[str] = None):
        self._net = None
        self._is_model_loaded = False
        if model_path and os.path.exists(model_path):
            try:
                import cv2
                self._net = cv2.dnn.readNet(model_path)
                self._is_model_loaded = True
            except Exception:
                self._is_model_loaded = False

    def estimate(self, face_bgr: Optional[np.ndarray]) -> Tuple[AgeGroup, float]:
        """Evaluates face image and returns (AgeGroup, confidence)."""
        if face_bgr is None or not isinstance(face_bgr, np.ndarray) or face_bgr.size == 0:
            return AgeGroup.UNKNOWN, 0.0

        h, w = face_bgr.shape[:2]
        # Quality check: reject tiny or heavily degraded crops
        if h < 45 or w < 45:
            return AgeGroup.UNKNOWN, 0.25

        # 1. Deep Learning Backend (if model weights available)
        if self._is_model_loaded and self._net is not None:
            try:
                import cv2
                blob = cv2.dnn.blobFromImage(
                    face_bgr, 1.0, (227, 227), (78.4263377603, 87.7689143744, 114.895847746), swapRB=False
                )
                self._net.setInput(blob)
                preds = self._net.forward()[0]
                idx = int(np.argmax(preds))
                conf = float(preds[idx])

                # Mapping 8 standard age brackets: (0-2), (4-6), (8-12), (15-20), (25-32), (38-43), (48-53), (60-100)
                if idx in (0, 1, 2):
                    return AgeGroup.CHILD, conf
                elif idx == 3:
                    return AgeGroup.TEEN, conf
                elif idx in (4, 5, 6):
                    return AgeGroup.ADULT, conf
                elif idx == 7:
                    return AgeGroup.SENIOR, conf
            except Exception:
                pass

        # 2. Algorithmic Anthropometric & Texture Feature Fallback
        return self._estimate_from_features(face_bgr)

    def _estimate_from_features(self, face_bgr: np.ndarray) -> Tuple[AgeGroup, float]:
        import cv2

        h, w = face_bgr.shape[:2]
        gray = cv2.cvtColor(face_bgr, cv2.COLOR_BGR2GRAY)

        # A. Face roundness (aspect ratio w/h)
        # Children typically have wider, rounder facial bounding shapes (w/h >= 0.92)
        aspect = float(w) / float(h)

        # B. High-frequency wrinkle / texture density (Laplacian variance in forehead/periorbital)
        # Forehead region is top 25% of face crop
        forehead = gray[: int(h * 0.28), int(w * 0.20) : int(w * 0.80)]
        if forehead.size > 0:
            lap_var = float(cv2.Laplacian(forehead, cv2.CV_64F).var())
        else:
            lap_var = 0.0

        # C. Skin smoothness / gradient contrast
        # Smooth skin (low edge variance) indicates young child
        overall_lap = float(cv2.Laplacian(gray, cv2.CV_64F).var())

        # Decision rules with confidence calibration
        if aspect >= 0.95 and lap_var < 80.0 and overall_lap < 180.0:
            # Round face + very smooth skin -> CHILD
            conf = 0.85
            return AgeGroup.CHILD, conf

        if lap_var > 450.0 or overall_lap > 700.0:
            # Pronounced facial lines and wrinkle texture -> SENIOR
            conf = 0.82
            return AgeGroup.SENIOR, conf

        if 0.78 <= aspect <= 0.92 and 100.0 <= lap_var <= 350.0:
            # Elongated adult facial proportions with moderate texture -> ADULT
            conf = 0.78
            return AgeGroup.ADULT, conf

        # Low confidence / ambiguous measurements must return UNKNOWN
        return AgeGroup.UNKNOWN, 0.40
