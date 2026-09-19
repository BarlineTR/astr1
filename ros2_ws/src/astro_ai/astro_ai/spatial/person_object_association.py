"""ASTRO V1 — Person-Object Spatial Association Engine.

Determines geometric and semantic relationships between tracked persons
and detected spatial objects (e.g. HOLDING, NEAR, IN_FRONT_OF, LOOKING_AT)
using 2D visual projection and 3D metric spatial coordinates.
"""

from dataclasses import dataclass
import math
import time
from typing import Dict, List, Optional, Tuple

from astro_ai.contracts.person_state import UnifiedPersonState
from astro_ai.contracts.spatial_state import SpatialObjectState


class InteractionType:
    HOLDING = "holding"
    NEAR = "near"
    IN_FRONT_OF = "in_front_of"
    LOOKING_AT = "looking_at"
    NONE = "none"


@dataclass
class AssociationResult:
    person_id: str
    object_id: str
    class_name: str
    relation: str
    confidence: float
    distance_m: float
    timestamp: float


class PersonObjectAssociator:
    """Computes spatial relationships between people and objects."""

    def __init__(self, proximity_threshold_m: float = 0.85):
        self.proximity_threshold_m = proximity_threshold_m

    def associate(
        self,
        people: List[UnifiedPersonState],
        objects: List[SpatialObjectState],
        now: Optional[float] = None,
    ) -> List[AssociationResult]:
        t = now if now is not None else time.time()
        results: List[AssociationResult] = []

        if not people or not objects:
            return results

        for person in people:
            if not getattr(person, "is_present", False):
                continue

            person_dist = getattr(person, "distance_m", 1.5) or 1.5
            person_yaw = getattr(person, "azimuth_deg", 0.0) or 0.0
            face_bbox = getattr(person, "face_bbox", None) or getattr(person, "raw_attributes", {}).get("face_bbox")

            interacting_classes = []

            for obj in objects:
                if (t - obj.last_observed_ts) > 3.0:
                    continue  # Skip stale objects

                has_metric_depth = (obj.distance_m > 0.0)
                obj_dist = obj.distance_m if has_metric_depth else person_dist
                rel_dist = abs(person_dist - obj_dist) if has_metric_depth else 0.50

                relation = InteractionType.NONE
                rel_conf = 0.0

                # 1. 2D Bounding Box Proximity (if face bbox is present)
                if face_bbox and obj.bbox and any(obj.bbox):
                    fx, fy, fw, fh = face_bbox
                    # Approximate torso / chest region below face
                    torso_xmin = fx - int(fw * 0.4)
                    torso_ymin = fy + int(fh * 0.8)
                    torso_xmax = fx + int(fw * 1.4)
                    torso_ymax = fy + int(fh * 3.5)

                    oxmin, oymin, oxmax, oymax = obj.bbox
                    ocx, ocy = obj.center
                    if ocx == 0.0 and ocy == 0.0 and any(obj.bbox):
                        ocx = (oxmin + oxmax) / 2.0
                        ocy = (oymin + oymax) / 2.0

                    # Check if object center is actually in mouth / chin region (for drinking/eating)
                    mouth_ymin = fy + int(fh * 0.4)
                    mouth_ymax = fy + int(fh * 1.35)
                    mouth_xmin = fx - int(fw * 0.3)
                    mouth_xmax = fx + int(fw * 1.3)

                    # Strict mouth overlap: object center must be in mouth zone and not a huge desk bbox
                    obj_height = oymax - oymin
                    is_near_mouth = (
                        mouth_xmin <= ocx <= mouth_xmax and
                        mouth_ymin <= ocy <= mouth_ymax and
                        obj_height <= int(fh * 2.2)
                    )

                    is_in_torso = (
                        oxmin < torso_xmax and oxmax > torso_xmin and
                        oymin < torso_ymax and oymax > torso_ymin
                    )

                    # Metric depth check: if depth is known, must be within 0.45m of person
                    depth_valid_for_holding = (not has_metric_depth) or (rel_dist <= 0.45)

                    if is_near_mouth and depth_valid_for_holding and obj.class_name in ("cup", "bottle", "wine glass", "fork", "spoon", "sandwich", "apple"):
                        relation = InteractionType.HOLDING
                        rel_conf = 0.90
                    elif is_in_torso and depth_valid_for_holding and obj.class_name in ("cell phone", "book"):
                        relation = InteractionType.HOLDING
                        rel_conf = 0.85
                    elif is_in_torso and obj.class_name in ("cup", "bottle", "wine glass"):
                        # Resting on desk in front of torso: NEAR, not drinking
                        relation = InteractionType.NEAR
                        rel_conf = 0.75
                    elif is_in_torso and obj.class_name in ("laptop", "keyboard"):
                        relation = InteractionType.IN_FRONT_OF
                        rel_conf = 0.88
                    elif rel_dist <= self.proximity_threshold_m:
                        relation = InteractionType.NEAR
                        rel_conf = max(0.40, 1.0 - (rel_dist / self.proximity_threshold_m))

                # 2. Metric 3D Proximity Fallback (when 2D face_bbox is absent)
                elif has_metric_depth and rel_dist <= self.proximity_threshold_m:
                    if obj.class_name in ("laptop", "keyboard") and obj_dist < person_dist:
                        relation = InteractionType.IN_FRONT_OF
                        rel_conf = 0.80
                    elif obj.class_name in ("cell phone", "book") and rel_dist < 0.35:
                        relation = InteractionType.HOLDING
                        rel_conf = 0.75
                    elif obj.class_name in ("cup", "bottle") and rel_dist < 0.25:
                        relation = InteractionType.HOLDING
                        rel_conf = 0.70
                    else:
                        relation = InteractionType.NEAR
                        rel_conf = max(0.40, 1.0 - (rel_dist / self.proximity_threshold_m))

                if relation != InteractionType.NONE:
                    # Update object contract fields
                    obj.associated_person_id = person.person_id
                    obj.interaction_type = relation
                    interacting_classes.append(obj.class_name)

                    res = AssociationResult(
                        person_id=person.person_id,
                        object_id=obj.object_id,
                        class_name=obj.class_name,
                        relation=relation,
                        confidence=round(rel_conf, 2),
                        distance_m=round(rel_dist, 2),
                        timestamp=t,
                    )
                    results.append(res)

            # Update person's interacting objects list
            setattr(person, "interacting_objects", list(set(interacting_classes)))

        return results
