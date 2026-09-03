"""Detection confidence for Haar cascade face detectors.

A cascade that publishes only bounding boxes tells the gaze stack nothing about
how good each detection was, and the stack's whole arbitration — the 0.50 validity
gate, the 0.75 acquisition / 0.40 hold hysteresis — then runs on a fabricated
constant. OpenCV already computes a per-detection stage weight; this maps it onto
the confidence scale those thresholds are written in.
"""

from typing import Any, List, Optional, Tuple

# Range of `levelWeights` from the default frontal-face cascades: a bare
# acceptance sits near zero, and a clean synthetic frontal face measured 8.27, so
# anything past the ceiling is already unambiguous and clamps. The ceiling is
# provisional — it was set from synthetic frames, and wants re-measuring against
# real camera footage of the robot's actual working distances.
HAAR_WEIGHT_FLOOR = 0.0
HAAR_WEIGHT_CEILING = 4.8

# The floor sits under VisualPerceptionCore's 0.50 validity gate on purpose, so a
# barely-accepted detection is discarded rather than tracked. The ceiling stays
# short of 1.0 because a Haar cascade never earns certainty.
CONFIDENCE_FLOOR = 0.40
CONFIDENCE_CEILING = 0.95


def haar_level_weight_to_confidence(level_weight: Optional[float]) -> float:
    """Maps one cascade stage weight onto a [CONFIDENCE_FLOOR..CONFIDENCE_CEILING] score.

    `level_weight` is None on OpenCV builds that expose no `detectMultiScale3`;
    that silence is treated as the weakest evidence, never as a good detection.
    """
    if level_weight is None:
        return CONFIDENCE_FLOOR

    span = HAAR_WEIGHT_CEILING - HAAR_WEIGHT_FLOOR
    ratio = (float(level_weight) - HAAR_WEIGHT_FLOOR) / span
    ratio = max(0.0, min(1.0, ratio))
    return CONFIDENCE_FLOOR + ratio * (CONFIDENCE_CEILING - CONFIDENCE_FLOOR)


def detect_faces_with_confidence(cascade: Any, image, **kwargs) -> List[Tuple[int, int, int, int, float]]:
    """Runs a cascade and returns (x, y, w, h, confidence) per detection.

    Prefers `detectMultiScale3`, the only entry point that hands back the stage
    weights; builds without it — and the import-less cv2 stub the vision nodes
    carry — fall back to the unscored call and the confidence floor.
    """
    weights = None
    if hasattr(cascade, "detectMultiScale3"):
        rects, _levels, weights = cascade.detectMultiScale3(image, outputRejectLevels=True, **kwargs)
    else:
        rects = cascade.detectMultiScale(image, **kwargs)

    faces: List[Tuple[int, int, int, int, float]] = []
    for idx, (x, y, w, h) in enumerate(rects):
        weight = weights[idx] if weights is not None and idx < len(weights) else None
        faces.append((int(x), int(y), int(w), int(h), haar_level_weight_to_confidence(weight)))
    return faces
