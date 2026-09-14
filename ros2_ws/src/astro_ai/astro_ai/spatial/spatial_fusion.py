"""ASTRO V1 — Multi-Sensory Spatial Fusion Engine.

Fuses OAK-D RGB-D Vision + ReSpeaker Acoustic DOA + RPLiDAR 2D planar tracking
into authoritative UnifiedPersonState instances.
"""

import math
import threading
import time
from typing import Any, Dict, List, Optional

from astro_ai.contracts.intent_emotion_types import EmotionSignal, RelationshipRole
from astro_ai.contracts.person_state import EntityLifecycleState, UnifiedPersonState
from astro_ai.contracts.spatial_state import SpatialPersonTrack
from astro_ai.spatial.epistemic_cone import evaluate_epistemic_grounding
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
        vad_active: Optional[bool] = None,
        rms_level: Optional[float] = None,
    ):
        """Updates cache with latest acoustic perception from audio_capture and voice_recognizer.

        Strict physical rule:
        - 0.0° uncalibrated default / idle reading without VAD/RMS is rejected.
        """
        with self._lock:
            validated_doa = doa_deg
            if doa_deg is not None:
                vad = vad_active if vad_active is not None else is_speaking
                if abs(float(doa_deg)) < 0.5 and not vad and (rms_level is None or rms_level < 450.0):
                    validated_doa = None

            self._latest_audio_doa = validated_doa
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
        """Performs evidence-based spatial alignment and association across Camera, Audio, and LiDAR.

        Does not forcibly fuse vision and audio if directions diverge significantly (>25°).
        Produces distinct VisualEntity and AcousticEntity when evidence is disjoint.
        """
        t_now = now or time.time()
        with self._lock:
            self._last_fusion_time = t_now
            lidar_tracks = self.lidar_tracker.get_active_tracks()
            fused_list: List[UnifiedPersonState] = []
            audio_associated = False

            # Case A: Visual Face(s) Detected
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

                    # Acoustic association with angular and identity evidence
                    voice_matched = False
                    spk_name = self._latest_speaker_data.get("name") if self._latest_speaker_data else None
                    angle_diff_audio = 999.0
                    if self._latest_audio_doa is not None:
                        angle_diff_audio = abs((self._latest_audio_doa - cam_yaw + 180.0) % 360.0 - 180.0)

                    if self._is_speaking:
                        if spk_name and name.lower() == spk_name.lower():
                            voice_matched = True
                            audio_associated = True
                        elif self._latest_audio_doa is not None and angle_diff_audio <= 25.0:
                            voice_matched = True
                            audio_associated = True

                    # Fused distance & velocity
                    fused_dist = matched_lidar_track.distance_m if matched_lidar_track else cam_dist
                    approach_vel = matched_lidar_track.velocity_mps if matched_lidar_track else 0.0
                    azimuth = matched_lidar_track.azimuth_deg if matched_lidar_track else cam_yaw

                    person_id = f"person_{name.lower().replace(' ', '_')}" if is_known else f"person_visual_{idx+1}"

                    # Determine lifecycle state from radial velocity
                    if approach_vel < -0.15:
                        lifecycle = EntityLifecycleState.APPROACHING
                    elif approach_vel > 0.15:
                        lifecycle = EntityLifecycleState.DEPARTING
                    else:
                        lifecycle = EntityLifecycleState.STATIONARY

                    has_lidar_flag = (matched_lidar_track is not None)
                    uncertainty = 0.05 if (has_lidar_flag and is_known) else (0.15 if (has_lidar_flag or voice_matched) else 0.35)
                    epistemic = evaluate_epistemic_grounding(
                        has_vision=True,
                        has_audio=voice_matched,
                        azimuth_deg=azimuth,
                        head_yaw_deg=0.0,
                        has_lidar=has_lidar_flag,
                    )

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
                        audio_doa_deg=self._latest_audio_doa if voice_matched else None,
                        voice_match_confidence=float(self._latest_speaker_data.get("confidence", 0.0)) if (self._latest_speaker_data and voice_matched) else 0.0,
                        last_seen_ts=t_now,
                        last_spoken_ts=t_now if (self._is_speaking and voice_matched) else 0.0,
                        tracking_state=lifecycle,
                        entity_type="PERSON",
                        has_vision=True,
                        has_lidar=has_lidar_flag,
                        has_audio=voice_matched,
                        spatial_uncertainty=uncertainty,
                        in_optical_cone=epistemic.in_camera_cone,
                        can_claim_vision=epistemic.can_claim_vision,
                        epistemic_status=epistemic.status.value,
                    )
                    fused_list.append(fused_person)
                    self._fused_people[person_id] = fused_person

                # Check if there is an unassociated active acoustic source (Disjoint Acoustic Entity)
                if self._is_speaking and self._latest_audio_doa is not None and not audio_associated:
                    # Match closest lidar track near audio direction if any
                    matched_lidar_audio = None
                    best_l_diff = 30.0
                    for tr in lidar_tracks:
                        ad = abs((tr.azimuth_deg - self._latest_audio_doa + 180.0) % 360.0 - 180.0)
                        if ad < best_l_diff:
                            best_l_diff = ad
                            matched_lidar_audio = tr

                    spk_name = self._latest_speaker_data.get("name", "Misafir") if self._latest_speaker_data else "Misafir"
                    a_dist = matched_lidar_audio.distance_m if matched_lidar_audio else 2.5
                    a_vel = matched_lidar_audio.velocity_mps if matched_lidar_audio else 0.0
                    a_pid = "audio_speaker_1"
                    for existing_pid, ep in self._fused_people.items():
                        if getattr(ep, "entity_type", "") == "ACOUSTIC_ENTITY":
                            adiff = abs((ep.azimuth_deg - self._latest_audio_doa + 180.0) % 360.0 - 180.0)
                            if adiff <= 25.0:
                                a_pid = existing_pid
                                break

                    epistemic_audio = evaluate_epistemic_grounding(
                        has_vision=False,
                        has_audio=True,
                        azimuth_deg=self._latest_audio_doa,
                        head_yaw_deg=0.0,
                        has_lidar=(matched_lidar_audio is not None),
                    )

                    acoustic_person = UnifiedPersonState(
                        person_id=a_pid,
                        name=spk_name,
                        formal_title=spk_name,
                        role=RelationshipRole.CREATOR if spk_name.lower() == "baran" else RelationshipRole.UNKNOWN,
                        is_known=(spk_name.lower() == "baran"),
                        identity_confidence=0.40 if self._latest_speaker_data else 0.20,
                        distance_m=round(a_dist, 2),
                        azimuth_deg=round(self._latest_audio_doa, 1),
                        x_m=round(a_dist * math.cos(math.radians(self._latest_audio_doa)), 2),
                        y_m=round(a_dist * math.sin(math.radians(self._latest_audio_doa)), 2),
                        approach_velocity_mps=round(a_vel, 2),
                        is_present=True,
                        is_looking_at_robot=False,
                        is_speaking=True,
                        audio_doa_deg=self._latest_audio_doa,
                        voice_match_confidence=float(self._latest_speaker_data.get("confidence", 0.0)) if self._latest_speaker_data else 0.0,
                        last_seen_ts=t_now,
                        last_spoken_ts=t_now,
                        tracking_state=EntityLifecycleState.APPROACHING if a_vel < -0.15 else (
                            EntityLifecycleState.DEPARTING if a_vel > 0.15 else EntityLifecycleState.STATIONARY
                        ),
                        entity_type="ACOUSTIC_ENTITY",
                        has_vision=False,
                        has_lidar=(matched_lidar_audio is not None),
                        has_audio=True,
                        spatial_uncertainty=0.40 if matched_lidar_audio else 0.65,
                        in_optical_cone=epistemic_audio.in_camera_cone,
                        can_claim_vision=epistemic_audio.can_claim_vision,
                        epistemic_status=epistemic_audio.status.value,
                    )
                    fused_list.append(acoustic_person)
                    self._fused_people[a_pid] = acoustic_person

            # Case B: LiDAR Only Dynamic Track(s) (Person outside camera FOV or in darkness)
            elif lidar_tracks:
                for tr in lidar_tracks:
                    if tr.distance_m < 4.0:
                        pid = f"person_spatial_{tr.track_id}"
                        is_audio_match = self._is_speaking and (
                            self._latest_audio_doa is not None
                            and abs((self._latest_audio_doa - tr.azimuth_deg + 180.0) % 360.0 - 180.0) < 30.0
                        )
                        if is_audio_match:
                            audio_associated = True

                        if tr.velocity_mps < -0.15:
                            lifecycle = EntityLifecycleState.APPROACHING
                        elif tr.velocity_mps > 0.15:
                            lifecycle = EntityLifecycleState.DEPARTING
                        else:
                            lifecycle = EntityLifecycleState.STATIONARY

                        epistemic_lidar = evaluate_epistemic_grounding(
                            has_vision=False,
                            has_audio=is_audio_match,
                            azimuth_deg=tr.azimuth_deg,
                            head_yaw_deg=0.0,
                            has_lidar=True,
                        )

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
                            is_speaking=is_audio_match,
                            audio_doa_deg=self._latest_audio_doa if is_audio_match else None,
                            last_seen_ts=t_now,
                            last_spoken_ts=t_now if is_audio_match else 0.0,
                            tracking_state=lifecycle,
                            entity_type="PERSON",
                            has_vision=False,
                            has_lidar=True,
                            has_audio=is_audio_match,
                            spatial_uncertainty=0.25,
                            in_optical_cone=epistemic_lidar.in_camera_cone,
                            can_claim_vision=epistemic_lidar.can_claim_vision,
                            epistemic_status=epistemic_lidar.status.value,
                        )
                        fused_list.append(fused_person)
                        self._fused_people[pid] = fused_person

                # If audio is speaking without nearby lidar track
                if self._is_speaking and self._latest_audio_doa is not None and not audio_associated:
                    spk_name = self._latest_speaker_data.get("name", "Misafir") if self._latest_speaker_data else "Misafir"
                    a_pid = "audio_speaker_1"
                    for existing_pid, ep in self._fused_people.items():
                        if getattr(ep, "entity_type", "") == "ACOUSTIC_ENTITY":
                            adiff = abs((ep.azimuth_deg - self._latest_audio_doa + 180.0) % 360.0 - 180.0)
                            if adiff <= 25.0:
                                a_pid = existing_pid
                                break
                    epistemic_audio = evaluate_epistemic_grounding(
                        has_vision=False,
                        has_audio=True,
                        azimuth_deg=self._latest_audio_doa,
                        head_yaw_deg=0.0,
                        has_lidar=False,
                    )
                    acoustic_person = UnifiedPersonState(
                        person_id=a_pid,
                        name=spk_name,
                        formal_title=spk_name,
                        role=RelationshipRole.CREATOR if spk_name.lower() == "baran" else RelationshipRole.UNKNOWN,
                        is_known=(spk_name.lower() == "baran"),
                        identity_confidence=0.40 if self._latest_speaker_data else 0.20,
                        distance_m=2.5,
                        azimuth_deg=round(self._latest_audio_doa, 1),
                        x_m=round(2.5 * math.cos(math.radians(self._latest_audio_doa)), 2),
                        y_m=round(2.5 * math.sin(math.radians(self._latest_audio_doa)), 2),
                        approach_velocity_mps=0.0,
                        is_present=True,
                        is_looking_at_robot=False,
                        is_speaking=True,
                        audio_doa_deg=self._latest_audio_doa,
                        voice_match_confidence=float(self._latest_speaker_data.get("confidence", 0.0)) if self._latest_speaker_data else 0.0,
                        last_seen_ts=t_now,
                        last_spoken_ts=t_now,
                        tracking_state=EntityLifecycleState.STATIONARY,
                        entity_type="ACOUSTIC_ENTITY",
                        has_vision=False,
                        has_lidar=False,
                        has_audio=True,
                        spatial_uncertainty=0.65,
                        in_optical_cone=epistemic_audio.in_camera_cone,
                        can_claim_vision=epistemic_audio.can_claim_vision,
                        epistemic_status=epistemic_audio.status.value,
                    )
                    fused_list.append(acoustic_person)
                    self._fused_people[a_pid] = acoustic_person

            # Case C: Audio Only (No vision, no LiDAR tracks, but valid acoustic speech)
            elif self._is_speaking and self._latest_audio_doa is not None:
                spk_name = self._latest_speaker_data.get("name", "Misafir") if self._latest_speaker_data else "Misafir"
                a_pid = "audio_speaker_1"
                for existing_pid, ep in self._fused_people.items():
                    if getattr(ep, "entity_type", "") == "ACOUSTIC_ENTITY":
                        adiff = abs((ep.azimuth_deg - self._latest_audio_doa + 180.0) % 360.0 - 180.0)
                        if adiff <= 25.0:
                            a_pid = existing_pid
                            break
                epistemic_audio = evaluate_epistemic_grounding(
                    has_vision=False,
                    has_audio=True,
                    azimuth_deg=self._latest_audio_doa,
                    head_yaw_deg=0.0,
                    has_lidar=False,
                )
                acoustic_person = UnifiedPersonState(
                    person_id=a_pid,
                    name=spk_name,
                    formal_title=spk_name,
                    role=RelationshipRole.CREATOR if spk_name.lower() == "baran" else RelationshipRole.UNKNOWN,
                    is_known=(spk_name.lower() == "baran"),
                    identity_confidence=0.40 if self._latest_speaker_data else 0.20,
                    distance_m=2.5,
                    azimuth_deg=round(self._latest_audio_doa, 1),
                    x_m=round(2.5 * math.cos(math.radians(self._latest_audio_doa)), 2),
                    y_m=round(2.5 * math.sin(math.radians(self._latest_audio_doa)), 2),
                    approach_velocity_mps=0.0,
                    is_present=True,
                    is_looking_at_robot=False,
                    is_speaking=True,
                    audio_doa_deg=self._latest_audio_doa,
                    voice_match_confidence=float(self._latest_speaker_data.get("confidence", 0.0)) if self._latest_speaker_data else 0.0,
                    last_seen_ts=t_now,
                    last_spoken_ts=t_now,
                    tracking_state=EntityLifecycleState.STATIONARY,
                    entity_type="ACOUSTIC_ENTITY",
                    has_vision=False,
                    has_lidar=False,
                    has_audio=True,
                    spatial_uncertainty=0.65,
                    in_optical_cone=epistemic_audio.in_camera_cone,
                    can_claim_vision=epistemic_audio.can_claim_vision,
                    epistemic_status=epistemic_audio.status.value,
                )
                fused_list.append(acoustic_person)
                self._fused_people[a_pid] = acoustic_person

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
