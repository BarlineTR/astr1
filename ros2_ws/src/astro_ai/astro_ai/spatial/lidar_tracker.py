"""ASTRO V1 — Real-Time LiDAR Clustering and Spatial Tracking Engine.

Processes 2D planar laser scans (RPLIDAR) into coherent spatial clusters,
tracks dynamic object velocities, and detects approach/departure events without high CPU load.
"""

import math
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from astro_ai.contracts.spatial_state import (
    LidarCluster,
    LidarScanSnapshot,
    SpatialPersonTrack,
)


class LidarTracker:
    """Fast LiDAR scan clusterer and velocity tracker."""

    def __init__(
        self,
        cluster_threshold_m: float = 0.28,
        min_cluster_points: int = 2,
        max_cluster_width_m: float = 1.1,
        person_min_width_m: float = 0.04,
        person_max_width_m: float = 0.95,
    ):
        self.cluster_threshold_m = cluster_threshold_m
        self.min_cluster_points = min_cluster_points
        self.max_cluster_width_m = max_cluster_width_m
        self.person_min_width_m = person_min_width_m
        self.person_max_width_m = person_max_width_m

        self._lock = threading.Lock()
        self._last_clusters: List[LidarCluster] = []
        self._active_tracks: Dict[str, SpatialPersonTrack] = {}
        self._track_seq = 0
        self._last_scan_time = 0.0

    def process_scan(
        self,
        ranges: List[float],
        angle_min: float = -math.pi,
        angle_increment: float = math.radians(1.0),
        range_min: float = 0.15,
        range_max: float = 12.0,
        timestamp: Optional[float] = None,
    ) -> LidarScanSnapshot:
        """Processes a raw 360-degree range array into clusters and updates tracking state."""
        now = timestamp or time.time()
        dt = max(0.01, now - self._last_scan_time) if self._last_scan_time > 0 else 0.1
        self._last_scan_time = now

        if not ranges:
            return LidarScanSnapshot(
                timestamp=now,
                min_front_distance_m=12.0,
                min_overall_distance_m=12.0,
                clusters=[],
                free_space_front=True,
                obstacle_detected_within_1m=False,
            )

        # 1. Convert valid ranges to Polar & Cartesian coordinates
        points_xy: List[Tuple[float, float, float, float]] = []  # (x, y, r, angle_deg)
        min_front_dist = range_max
        min_overall_dist = range_max

        num_ranges = len(ranges)
        for i, r in enumerate(ranges):
            if math.isnan(r) or math.isinf(r) or r < range_min or r > range_max:
                continue

            angle = angle_min + (i * angle_increment)
            angle_deg = math.degrees(angle)
            # Normalize angle_deg to [-180, +180]
            angle_deg = (angle_deg + 180.0) % 360.0 - 180.0

            x = r * math.cos(angle)
            y = r * math.sin(angle)
            points_xy.append((x, y, r, angle_deg))

            if r < min_overall_dist:
                min_overall_dist = r

            # Check +/- 35 degree front cone
            if abs(angle_deg) <= 35.0 and r < min_front_dist:
                min_front_dist = r

        # 2. Euclidean Distance Point Clustering
        clusters: List[LidarCluster] = []
        if points_xy:
            curr_cluster_pts = [points_xy[0]]
            cluster_id = 1

            for p in points_xy[1:]:
                prev_p = curr_cluster_pts[-1]
                # Euclidean distance between consecutive scan points
                dist = math.hypot(p[0] - prev_p[0], p[1] - prev_p[1])
                # Adaptive threshold proportional to distance
                adaptive_thresh = self.cluster_threshold_m + (0.04 * prev_p[2])

                if dist <= adaptive_thresh:
                    curr_cluster_pts.append(p)
                else:
                    cl = self._build_cluster(cluster_id, curr_cluster_pts, now)
                    if cl is not None:
                        clusters.append(cl)
                        cluster_id += 1
                    curr_cluster_pts = [p]

            # Last cluster
            if curr_cluster_pts:
                cl = self._build_cluster(cluster_id, curr_cluster_pts, now)
                if cl is not None:
                    clusters.append(cl)

        # 3. Update Temporal Tracks & Velocity
        with self._lock:
            self._update_tracks(clusters, dt, now)
            self._last_clusters = clusters

        return LidarScanSnapshot(
            timestamp=now,
            min_front_distance_m=round(min_front_dist, 2),
            min_overall_distance_m=round(min_overall_dist, 2),
            clusters=clusters,
            free_space_front=min_front_dist > 1.2,
            obstacle_detected_within_1m=min_front_dist < 1.0,
        )

    def _build_cluster(
        self,
        cid: int,
        pts: List[Tuple[float, float, float, float]],
        timestamp: float,
    ) -> Optional[LidarCluster]:
        if len(pts) < self.min_cluster_points:
            return None

        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        rs = [p[2] for p in pts]
        angles = [p[3] for p in pts]

        center_x = float(np.mean(xs))
        center_y = float(np.mean(ys))
        center_r = float(np.mean(rs))
        center_az = float(np.mean(angles))

        width = float(math.hypot(xs[-1] - xs[0], ys[-1] - ys[0]))
        if width > self.max_cluster_width_m:
            return None

        return LidarCluster(
            cluster_id=cid,
            center_distance_m=round(center_r, 3),
            center_azimuth_deg=round(center_az, 1),
            x_m=round(center_x, 3),
            y_m=round(center_y, 3),
            point_count=len(pts),
            width_m=round(width, 3),
            min_distance_m=round(min(rs), 3),
            max_distance_m=round(max(rs), 3),
            timestamp=timestamp,
        )

    def _update_tracks(self, clusters: List[LidarCluster], dt: float, now: float):
        """Associates new clusters with existing tracks using nearest neighbor gating."""
        matched_track_ids = set()

        for cl in clusters:
            best_track_id = None
            min_dist = 0.85  # 85cm dynamic gating radius

            for tid, tr in self._active_tracks.items():
                d = math.hypot(cl.x_m - tr.current_x, cl.y_m - tr.current_y)
                if d < min_dist:
                    min_dist = d
                    best_track_id = tid

            if best_track_id is not None:
                tr = self._active_tracks[best_track_id]
                prev_dist = tr.distance_m
                # Velocity: negative when approaching robot
                vel = (cl.center_distance_m - prev_dist) / dt
                cl.radial_velocity_mps = round(vel, 2)
                cl.is_dynamic = abs(vel) > 0.12

                tr.current_x = cl.x_m
                tr.current_y = cl.y_m
                tr.distance_m = cl.center_distance_m
                tr.azimuth_deg = cl.center_azimuth_deg
                tr.velocity_mps = round(vel, 2)
                tr.last_update_ts = now
                matched_track_ids.add(best_track_id)
            else:
                # Spawn new track if within human-like bounding size
                if self.person_min_width_m <= cl.width_m <= self.person_max_width_m and cl.center_distance_m < 6.0:
                    self._track_seq += 1
                    tid = f"track_{self._track_seq}"
                    self._active_tracks[tid] = SpatialPersonTrack(
                        track_id=tid,
                        current_x=cl.x_m,
                        current_y=cl.y_m,
                        distance_m=cl.center_distance_m,
                        azimuth_deg=cl.center_azimuth_deg,
                        velocity_mps=0.0,
                        heading_deg=0.0,
                        last_update_ts=now,
                    )
                    matched_track_ids.add(tid)

        # Prune stale tracks (> 2.0s without observation)
        stale = [
            tid for tid, tr in self._active_tracks.items()
            if (now - tr.last_update_ts) > 2.0
        ]
        for tid in stale:
            del self._active_tracks[tid]

    def get_active_tracks(self) -> List[SpatialPersonTrack]:
        with self._lock:
            return list(self._active_tracks.values())

    def get_closest_person_candidate(self) -> Optional[SpatialPersonTrack]:
        with self._lock:
            if not self._active_tracks:
                return None
            return min(self._active_tracks.values(), key=lambda t: t.distance_m)
