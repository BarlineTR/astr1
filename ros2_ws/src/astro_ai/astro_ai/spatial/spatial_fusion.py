"""ASTRO V1 — Multi-Sensory Spatial Fusion Engine.

Fuses OAK-D RGB-D Vision + ReSpeaker Acoustic DOA + RPLiDAR 2D planar tracking
into authoritative UnifiedPersonState instances.
"""

import math
import threading
import time
from typing import Any, Dict, List, Optional

from astro_ai.contracts.intent_emotion_types import EmotionSignal, RelationshipRole
from astro_ai.contracts.person_state import UnifiedPersonState
from astro_ai.contracts.spatial_state import SpatialPersonTrack
from astro_ai.spatial.lidar_tracker import LidarTracker


class SpatialFusionEngine:
    """Fuses multi-modal sensory streams into a coherent 3D spatial and identity model."""

    def __init__(self, lidar_tracker: Optional[LidarTracker] = None):
        self.lidar_tracker = lidar_tracker or LidarTracker()
        self._lock = threading.RLock()

        # Temporary perception caches
        self._latest_face_data: List[Dict[str, Any]] = []
        self._latest_speaker_data: Optional[Dict[str, Any]] = None
        self._latest_audio_doa: Optional[float] = None
        self._vision_looking = False
        self._vision_distance = 0.0
        self._vision_emotion = "neutral"
        self._is_speaking = False
        self._fused_people: Dict[str, UnifiedPersonState] = {}
        self._last_fusion_time = 0.0

    def update_vision_perception(
        self,
        faces: List[Dict[str, Any]],
        looking_at_robot: bool = False,
        user_distance_m: float = 0.0,
        user_emotion: str = "neutral",
    ):
        """Updates cache with latest frame detection from face_detector / oak_spatial node."""
        with self._lock:
            self._latest_face_data = faces or []
            self._vision_looking = looking_at_robot
            self._vision_distance = user_distance_m
            self._vision_emotion = user_emotion

    def update_audio_perception(
        self,
        doa_deg: Optional[float] = None,
        speaker_id_dict: Optional[Dict[str, Any]] = None,
        is_speaking: bool = False,
    ):
        """Updates cache with latest acoustic perception from audio_capture and voice_recognizer."""
        with self._lock:
            self._latest_audio_doa = doa_deg
            self._latest_speaker_data = speaker_id_dict
            self._is_speaking = is_speaking

    def update_lidar_scan(
        self,
        ranges: List[float],
        angle_min: float = -math.pi,
        angle_increment: float = math.radians(1.0),
        range_min: float = 0.15,
        range_max: float = 12.0,
    ):
        """Updates LiDAR tracker with a new LaserScan message."""
        return self.lidar_tracker.process_scan(
            ranges=ranges,
            angle_min=angle_min,
            angle_increment=angle_increment,
            range_min=range_min,
            range_max=range_max,
        )

    def compute_fusion(self, now: Optional[float] = None) -> List[UnifiedPersonState]:
        """Performs spatial alignment and association across Camera, Audio, and LiDAR."""
        t_now = now or time.time()
        with self._lock:
            self._last_fusion_time = t_now
            lidar_tracks = self.lidar_tracker.get_active_tracks()
            fused_list: List[UnifiedPersonState] = []

            # Case A: Visual Face Detected
            if self._latest_face_data:
                for idx, face in enumerate(self._latest_face_data):
                    name = face.get("name", "Misafir")
                    is_known = face.get("is_known", False)
                    conf = float(face.get("confidence", 0.0))
                    formal_title = face.get("formal_title", name)

                    # Estimate 3D distance and azimuth from face bounding box or depth
                    cam_dist = float(face.get("distance_m", self._vision_distance or 1.2))
                    cam_yaw = float(face.get("head_yaw_deg", 0.0))
                    looking = face.get("is_looking", self._vision_looking)

                    # Match closest LiDAR track within angular window
                    matched_lidar_track = None
                    best_angle_diff = 25.0  # 25 degree match tolerance

                    for tr in lidar_tracks:
                        angle_diff = abs(tr.azimuth_deg - cam_yaw)
                        dist_diff = abs(tr.distance_m - cam_dist)
                        if angle_diff < best_angle_diff and dist_diff < 1.0:
                            best_angle_diff = angle_diff
                            matched_lidar_track = tr

                    # Acoustic association
                    voice_matched = False
                    spk_name = self._latest_speaker_data.get("name") if self._latest_speaker_data else None
                    if self._is_speaking and spk_name:
                        if name.lower() == spk_name.lower():
                            voice_matched = True

                    # Fused distance & velocity
                    fused_dist = matched_lidar_track.distance_m if matched_lidar_track else cam_dist
                    approach_vel = matched_lidar_track.velocity_mps if matched_lidar_track else 0.0
                    azimuth = matched_lidar_track.azimuth_deg if matched_lidar_track else cam_yaw

                    person_id = f"person_{name.lower().replace(' ', '_')}" if is_known else f"person_visual_{idx+1}"

                    fused_person = UnifiedPersonState(
                        person_id=person_id,
                        name=name,
                        formal_title=formal_title,
                        role=RelationshipRole.CREATOR if name.lower() == "baran" else (RelationshipRole.FRIEND if is_known else RelationshipRole.UNKNOWN),
                        is_known=is_known,
                        identity_confidence=max(conf, 0.70 if is_known else 0.30),
                        distance_m=round(fused_dist, 2),
                        azimuth_deg=round(azimuth, 1),
                        x_m=round(fused_dist * math.cos(math.radians(azimuth)), 2),
                        y_m=round(fused_dist * math.sin(math.radians(azimuth)), 2),
                        approach_velocity_mps=round(approach_vel, 2),
                        is_present=True,
                        is_looking_at_robot=looking,
                        visual_emotion=EmotionSignal(self._vision_emotion.lower()) if self._vision_emotion.lower() in [e.value for e in EmotionSignal] else EmotionSignal.NEUTRAL,
                        visual_confidence=conf,
                        is_speaking=self._is_speaking and voice_matched,
                        audio_doa_deg=self._latest_audio_doa,
                        voice_match_confidence=float(self._latest_speaker_data.get("confidence", 0.0)) if (self._latest_speaker_data and voice_matched) else 0.0,
                        last_seen_ts=t_now,
                    )
                    fused_list.append(fused_person)
                    self._fused_people[person_id] = fused_person

            # Case B: LiDAR Only Dynamic Track (Person approaching from side/behind or in dark)
            elif lidar_tracks:
                for tr in lidar_tracks:
                    if tr.distance_m < 4.0:
                        pid = f"person_spatial_{tr.track_id}"
                        fused_person = UnifiedPersonState(
                            person_id=pid,
                            name="Misafir",
                            formal_title="Misafir",
                            role=RelationshipRole.UNKNOWN,
                            is_known=False,
                            identity_confidence=0.20,
                            distance_m=round(tr.distance_m, 2),
                            azimuth_deg=round(tr.azimuth_deg, 1),
                            x_m=round(tr.current_x, 2),
                            y_m=round(tr.current_y, 2),
                            approach_velocity_mps=round(tr.velocity_mps, 2),
                            is_present=True,
                            is_looking_at_robot=False,
                            is_speaking=self._is_speaking and (self._latest_audio_doa and abs(self._latest_audio_doa - tr.azimuth_deg) < 30.0),
                            audio_doa_deg=self._latest_audio_doa,
                            last_seen_ts=t_now,
                        )
                        fused_list.append(fused_person)
                        self._fused_people[pid] = fused_person

            return fused_list

    def get_fused_primary_person(self) -> Optional[UnifiedPersonState]:
        """Returns the most relevant person based on gaze, proximity, and speech activity."""
        with self._lock:
            people = self.compute_fusion()
            if not people:
                return None

            # Priority 1: Actively speaking person
            speakers = [p for p in people if p.is_speaking]
            if speakers:
                return min(speakers, key=lambda p: p.distance_m)

            # Priority 2: Person looking at robot
            lookers = [p for p in people if p.is_looking_at_robot]
            if lookers:
                return min(lookers, key=lambda p: p.distance_m)

            # Priority 3: Closest person
            return min(people, key=lambda p: p.distance_m)
