"""ASTRO V1 — Real Visual Attribute Extraction Engine.

Measures low-level physical visual attributes from camera pixel ROIs:
- Upper-body dominant clothing color (HSV/Lab color space binning with skin filtering)
- Optical accessories (glasses, eyewear from eye ROI contrast/edge profiles)
- Facial expression (smile ratio / neutral baseline)
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np


@dataclass
class VisualAttributes:
    """Measurable physical visual attributes observed on a person."""

    dominant_clothing_color: str = ""
    dominant_clothing_color_tr: str = ""
    clothing_color_confidence: float = 0.0
    accessories: List[str] = field(default_factory=list)
    expression: str = "neutral"
    expression_confidence: float = 0.50

    def to_dict(self) -> Dict[str, Any]:
        return {
            "dominant_clothing_color": self.dominant_clothing_color,
            "dominant_clothing_color_tr": self.dominant_clothing_color_tr,
            "clothing_color_confidence": round(float(self.clothing_color_confidence), 2),
            "accessories": list(self.accessories),
            "expression": self.expression,
            "expression_confidence": round(float(self.expression_confidence), 2),
        }


class VisualAttributeExtractor:
    """Extracts objective, verifiable visual attributes from RGB frames and face bboxes."""

    COLOR_MAP_TR = {
        "black": "siyah",
        "white": "beyaz",
        "gray": "gri",
        "blue": "mavi",
        "navy": "lacivert",
        "red": "kırmızı",
        "green": "yeşil",
        "yellow": "sarı",
        "brown": "kahverengi",
    }

    def extract(
        self,
        image_bgr: Optional[np.ndarray],
        face_bbox: Optional[Tuple[int, int, int, int]],
        is_smiling: bool = False,
    ) -> VisualAttributes:
        if image_bgr is None or face_bbox is None or not any(face_bbox):
            return VisualAttributes()

        img_h, img_w = image_bgr.shape[:2]
        fx, fy, fw, fh = face_bbox

        # 1. Torso ROI Extraction (Region directly below face)
        torso_x1 = max(0, fx - int(fw * 0.25))
        torso_x2 = min(img_w, fx + int(fw * 1.25))
        torso_y1 = min(img_h, fy + int(fh * 1.05))
        torso_y2 = min(img_h, fy + int(fh * 3.2))

        clothing_color = ""
        clothing_conf = 0.0

        if (torso_y2 - torso_y1) > 20 and (torso_x2 - torso_x1) > 20:
            torso_roi = image_bgr[torso_y1:torso_y2, torso_x1:torso_x2]
            clothing_color, clothing_conf = self._compute_dominant_clothing_color(torso_roi)

        # 2. Eye ROI Accessory Extraction (Glasses detection)
        accessories: List[str] = []
        eye_y1 = fy + int(fh * 0.25)
        eye_y2 = fy + int(fh * 0.55)
        eye_x1 = fx + int(fw * 0.15)
        eye_x2 = fx + int(fw * 0.85)

        if 0 <= eye_y1 < eye_y2 <= img_h and 0 <= eye_x1 < eye_x2 <= img_w:
            eye_roi = image_bgr[eye_y1:eye_y2, eye_x1:eye_x2]
            if self._detect_glasses(eye_roi):
                accessories.append("glasses")

        # 3. Expression
        expr = "smiling" if is_smiling else "neutral"
        expr_conf = 0.85 if is_smiling else 0.70

        color_tr = self.COLOR_MAP_TR.get(clothing_color, clothing_color)
        return VisualAttributes(
            dominant_clothing_color=clothing_color,
            dominant_clothing_color_tr=color_tr,
            clothing_color_confidence=clothing_conf,
            accessories=accessories,
            expression=expr,
            expression_confidence=expr_conf,
        )

    def _compute_dominant_clothing_color(self, bgr_roi: np.ndarray) -> Tuple[str, float]:
        """Calculates dominant color from HSV channels, masking out neck/skin tones."""
        hsv = cv2.cvtColor(bgr_roi, cv2.COLOR_BGR2HSV)
        h = hsv[:, :, 0]
        s = hsv[:, :, 1]
        v = hsv[:, :, 2]

        total_pixels = bgr_roi.shape[0] * bgr_roi.shape[1]
        if total_pixels == 0:
            return "", 0.0

        # Mask out human skin tones (Hue ~0-25, Sat ~30-170, Val > 60)
        skin_mask = (h < 25) & (s >= 30) & (s <= 170) & (v >= 60)
        valid_mask = ~skin_mask
        valid_count = int(np.sum(valid_mask))

        if valid_count < (total_pixels * 0.20):
            # If torso mostly skin or occluded, use full ROI
            valid_mask = np.ones((bgr_roi.shape[0], bgr_roi.shape[1]), dtype=bool)
            valid_count = total_pixels

        v_sub = v[valid_mask]
        s_sub = s[valid_mask]
        h_sub = h[valid_mask]

        # Black / Dark
        black_cnt = np.sum(v_sub < 50)
        # White / Bright Neutral
        white_cnt = np.sum((s_sub < 35) & (v_sub >= 195))
        # Gray / Neutral
        gray_cnt = np.sum((s_sub < 40) & (v_sub >= 50) & (v_sub < 195))
        # Blue / Navy
        navy_cnt = np.sum((h_sub >= 100) & (h_sub <= 135) & (v_sub < 110) & (s_sub >= 45))
        blue_cnt = np.sum((h_sub >= 100) & (h_sub <= 135) & (v_sub >= 110) & (s_sub >= 45))
        # Red
        red_cnt = np.sum(((h_sub < 10) | (h_sub > 168)) & (s_sub >= 65) & (v_sub >= 60))
        # Green
        green_cnt = np.sum((h_sub >= 35) & (h_sub <= 85) & (s_sub >= 50) & (v_sub >= 50))
        # Yellow
        yellow_cnt = np.sum((h_sub >= 20) & (h_sub < 35) & (s_sub >= 65) & (v_sub >= 120))

        counts = {
            "black": black_cnt,
            "white": white_cnt,
            "gray": gray_cnt,
            "navy": navy_cnt,
            "blue": blue_cnt,
            "red": red_cnt,
            "green": green_cnt,
            "yellow": yellow_cnt,
        }

        best_color, best_cnt = max(counts.items(), key=lambda item: item[1])
        conf = float(best_cnt) / float(valid_count)

        if conf >= 0.40:
            return best_color, round(conf, 2)
        return "", 0.0

    def _detect_glasses(self, eye_roi: np.ndarray) -> bool:
        """Detects eyewear by analyzing strong horizontal gradient edges across nasal bridge."""
        if eye_roi.size == 0 or eye_roi.shape[0] < 8 or eye_roi.shape[1] < 16:
            return False
        gray = cv2.cvtColor(eye_roi, cv2.COLOR_BGR2GRAY)
        # Nasal bridge is center horizontal strip
        mid_x1 = int(eye_roi.shape[1] * 0.35)
        mid_x2 = int(eye_roi.shape[1] * 0.65)
        bridge = gray[:, mid_x1:mid_x2]
        sobel_x = cv2.Sobel(bridge, cv2.CV_64F, 1, 0, ksize=3)
        edge_energy = float(np.mean(np.abs(sobel_x)))
        return edge_energy > 35.0
