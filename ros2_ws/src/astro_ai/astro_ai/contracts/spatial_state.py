"""ASTRO V1 — Spatial Perception and LiDAR Data Contracts."""

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class LidarCluster:
    """Represents a continuous spatial point cluster detected by LiDAR."""

    cluster_id: int
    center_distance_m: float
    center_azimuth_deg: float
    x_m: float
    y_m: float
    point_count: int
    width_m: float
    min_distance_m: float
    max_distance_m: float
    is_dynamic: bool = False
    radial_velocity_mps: float = 0.0  # + = approaching, - = retreating
    timestamp: float = field(default_factory=time.time)


@dataclass
class LidarScanSnapshot:
    """Processed summary of a single 360-degree LiDAR sweep."""

    timestamp: float
    min_front_distance_m: float
    min_overall_distance_m: float
    clusters: List[LidarCluster] = field(default_factory=list)
    free_space_front: bool = True
    obstacle_detected_within_1m: bool = False


@dataclass
class SpatialPersonTrack:
    """High-level spatial track of a person in the environment."""

    track_id: str
    current_x: float
    current_y: float
    distance_m: float
    azimuth_deg: float
    velocity_mps: float
    heading_deg: float
    last_update_ts: float
    associated_camera_face_id: Optional[str] = None
    associated_speaker_id: Optional[str] = None
    consecutive_approaching_count: int = 0
    is_dynamic: bool = False


@dataclass
class SpatialObjectState:
    """Represents a known or recognized object in 2D/3D robot coordinates."""

    object_name: str = ""
    category: str = ""
    x_m: float = 0.0
    y_m: float = 0.0
    z_m: float = 0.0
    is_static: bool = True
    confidence: float = 1.0
    last_observed_ts: float = field(default_factory=time.time)

    # Real Perception Extensions (Phase 1)
    object_id: str = ""
    class_name: str = ""
    distance_m: float = 0.0
    bbox: Tuple[int, int, int, int] = (0, 0, 0, 0)  # (xmin, ymin, xmax, ymax)
    center: Tuple[float, float] = (0.0, 0.0)        # (cx, cy)
    first_observed_ts: float = field(default_factory=time.time)
    source_frame_id: str = "oak_rgb_optical_frame"
    freshness: str = "FRESH"  # "FRESH", "STALE", "EXPIRED"
    associated_person_id: Optional[str] = None
    interaction_type: Optional[str] = None  # "holding", "near", "looking_at", "in_front_of"

    def __post_init__(self):
        if not self.class_name and self.category:
            self.class_name = self.category
        elif not self.category and self.class_name:
            self.category = self.class_name

        if not self.object_name and self.class_name:
            self.object_name = f"{self.class_name}_{self.object_id}" if self.object_id else self.class_name
        elif not self.object_id and self.object_name:
            self.object_id = self.object_name

        if self.distance_m == 0.0 and (self.x_m != 0.0 or self.y_m != 0.0 or self.z_m != 0.0):
            import math
            self.distance_m = math.sqrt(self.x_m ** 2 + self.y_m ** 2 + self.z_m ** 2)
