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


@dataclass
class SpatialObjectState:
    """Represents a known or recognized object in 3D robot coordinates."""

    object_name: str
    category: str
    x_m: float
    y_m: float
    z_m: float
    is_static: bool = True
    confidence: float = 1.0
    last_observed_ts: float = field(default_factory=time.time)
