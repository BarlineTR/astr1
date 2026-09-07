#!/usr/bin/env python3
"""Authoritative Gaze Decision Core for ASTRO Robot Head.

Shared decision core providing 5-state gaze ownership:
  - VISUAL_LOCK: Authoritative visual tracking via pinhole camera projection
  - VISUAL_COAST: Target coasting during temporary visual occlusion/dropouts
  - AUDIO_REACQUISITION: Verified speech orienting intent (never raw DOA)
  - VISUAL_HANDOVER: Seamless immediate handover on first valid visual acquisition
  - IDLE: Stationary hold in silence or when out of conversational envelope

This core is the single source of truth for both standalone execution and ROS 2.
"""

from dataclasses import dataclass, replace
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

from astro_base.gaze.angle_math import angular_diff_deg
from astro_base.gaze.audio_filter import AudioFilterCore
from astro_base.gaze.audio_perception import AudioPerceptionCore
from astro_base.gaze.coordinate_frames import (
    CalibrationConfig,
    CoordinateTransformer,
)
from astro_base.gaze.gaze_state_machine import SocialGazeFSM
from astro_base.gaze.motion_planner import MotionPlannerCore
from astro_base.gaze.sensor_fusion import AudioVisualFusionCore
from astro_base.gaze.spatial_memory import EpistemicSpatialMemory
from astro_base.gaze.target_manager import TargetManagerCore
from astro_base.gaze.types import (
    GazeStateEnum,
    Modality,
    PrioritySource,
    TrackingState,
)
from astro_base.gaze.visual_perception import VisualPerceptionCore
from astro_base.gaze.visual_tracker import VisualTrackerCore


@dataclass
class Detection:
    """One face box, in pixels, as the detector reports it."""
    x: int
    y: int
    w: int
    h: int
    confidence: Optional[float] = None
    detector_source: Optional[str] = None


@dataclass(frozen=True)
class GazeResult:
    """What the pipeline decided this cycle."""
    target_yaw_deg: float
    gaze_state: GazeStateEnum
    owner: PrioritySource
    target_id: Optional[str]
    confidence: float
    head_angle_deg: float
    face_bearings_deg: Tuple[float, ...] = ()
    target_source: str = "NONE"
    visual_target: bool = False
    audio_evidence: bool = False
    command_source: str = "SAFETY_ZERO"
    commands_from_audio: int = 0
    audio_bearing_valid: bool = False
    audio_bearing: float = 0.0
    audio_bearing_age_ms: float = 0.0
    visual_target_age_ms: float = 0.0
    coast_active: bool = False
    audio_reacquisition_active: bool = False
    audio_reacquisition_count: int = 0
    visual_handover_count: int = 0
    forensic: Optional[dict] = None
    active_target_at_command: str = "NONE"
    active_track_at_command: str = "NONE"
    command_generation_reason: str = "NONE"


# A detection whose publisher reports no confidence: over the target manager's 0.40
# hold threshold, under its 0.75 acquisition one, so an unscored frame alone cannot
# seize the head.
UNSCORED_CONFIDENCE = 0.65

DEFAULT_CALIBRATION_PATH = (Path(__file__).resolve().parents[2]
                            / "config" / "calibration_params.yaml")


def _load_calibration(path=None) -> CalibrationConfig:
    """Reads the shared calibration, falling back to defaults if it is not there."""
    candidate = Path(path) if path is not None else DEFAULT_CALIBRATION_PATH
    try:
        return CalibrationConfig.load_yaml(str(candidate))
    except (OSError, ValueError):
        return CalibrationConfig()


class GazeTracker:
    """Holds the shared gaze objects and steps them once per frame."""

    def __init__(self, calibration: Optional[CalibrationConfig] = None,
                 calibration_path=None, fallback_enabled: bool = False,
                 coast_timeout_s: float = 1.0):
        self.calib = calibration or _load_calibration(calibration_path)
        self.transformer = CoordinateTransformer(self.calib)
        self.spatial_memory = EpistemicSpatialMemory()

        self.visual_perception = VisualPerceptionCore(transformer=self.transformer)
        self.visual_tracker = VisualTrackerCore(transformer=self.transformer)
        self.audio_perception = AudioPerceptionCore(transformer=self.transformer)
        self.audio_filter = AudioFilterCore()
        self.fusion = AudioVisualFusionCore(
            spatial_memory=self.spatial_memory,
            fallback_enabled=fallback_enabled,
        )
        self.target_manager = TargetManagerCore()
        self.fsm = SocialGazeFSM(
            min_limit_deg=self.calib.head.min_angle_deg,
            max_limit_deg=self.calib.head.max_angle_deg,
            spatial_memory=self.spatial_memory,
        )
        self.planner = MotionPlannerCore(
            min_limit_deg=self.calib.head.min_angle_deg,
            max_limit_deg=self.calib.head.max_angle_deg,
        )

        self.head_angle_deg: float = 0.0
        self.head_velocity_deg_s: float = 0.0
        self.head_feedback_missing: bool = True
        self.commands_from_audio: int = 0
        self.commands_from_visual: int = 0
        self.audio_reacquisition_count: int = 0
        self.visual_handover_count: int = 0

        self.coast_timeout_s: float = float(coast_timeout_s)
        self._last_visual_target_yaw: Optional[float] = None
        self._last_visual_seen_time: float = 0.0
        self._last_visual_target_id: Optional[str] = None
        self._was_visually_tracking: bool = False

        self._audio_reacq_active: bool = False
        self._audio_reacq_target_yaw: Optional[float] = None
        self._audio_reacq_start_time: float = 0.0
        self._speech_in_progress: bool = False

        # Forensic telemetry state
        self._frame_index: int = 0
        self._last_target_yaw_telemetry: float = 0.0
        self._latest_detections_telemetry: List[dict] = []
        self.last_forensic_chain: Optional[dict] = None

        self._latest_audio = None
        self._latest_tracks: List = []

    def step(
        self,
        faces: Sequence[Detection],
        frame_size: Tuple[int, int],
        doa_deg: Optional[float],
        measured_head_deg: Optional[float],
        timestamp: float,
        speech=None,
        is_robot_speaking: bool = False,
    ) -> GazeResult:
        """Runs one cycle: perception, fusion, arbitration, motion."""
        self._frame_index += 1
        if measured_head_deg is not None:
            self.head_angle_deg = float(measured_head_deg)
            self.head_feedback_missing = False

        if doa_deg is not None and speech is not None and speech.is_speech:
            self._ingest_audio(doa_deg, timestamp, float(speech.confidence),
                               is_robot_speaking)

        self._ingest_vision(faces, frame_size, timestamp)

        # 1. Target-Manager telemetry snapshot before update
        prev_target = self.target_manager.active_target
        prev_target_id = prev_target.target_id if prev_target else "NONE"

        fused = self.fusion.fuse(self._latest_audio, self._latest_tracks, timestamp)
        target_state = self.target_manager.update(fused, timestamp)

        # 1. Target-Manager telemetry snapshot after update
        new_target = target_state.active_target
        new_target_id = new_target.target_id if new_target else "NONE"

        if self.target_manager.last_target_birth is not None:
            tm_reason = self.target_manager.last_target_birth.get("reason", f"TARGET_BIRTH_{new_target_id}")
        elif prev_target is None and new_target is not None:
            tm_reason = f"TARGET_ACQUIRED_{new_target.target_id}_{new_target.modality.value}"
        elif prev_target is not None and new_target is None:
            tm_reason = f"TARGET_LOST_{prev_target.target_id}"
        elif prev_target is not None and new_target is not None and prev_target.target_id != new_target.target_id:
            tm_reason = f"TURN_TAKING_SWITCH_{prev_target.target_id}_TO_{new_target.target_id}"
        elif prev_target is not None and new_target is not None and prev_target.target_id == new_target.target_id:
            tm_reason = f"TARGET_MAINTAINED_{new_target.target_id}"
        else:
            tm_reason = "NO_ACTIVE_TARGET"

        tm_telemetry = {
            "previous_active_target": prev_target_id,
            "new_active_target": new_target_id,
            "reason": tm_reason,
        }

        # 2. Attention decision telemetry snapshot before update
        old_owner = self.fsm.active_priority.value

        command = self.fsm.update(
            target_state=target_state,
            actual_head_yaw_deg=self.head_angle_deg,
            timestamp=timestamp,
            actual_head_vel_deg_s=self.head_velocity_deg_s,
        )

        # 2. Attention decision telemetry snapshot after update
        new_owner = self.fsm.active_priority.value
        decision = self.fsm.last_decision
        att_reason = decision.reason if decision else self.fsm.last_transition_reason
        preempted_target = (
            decision.preempted_target_id
            if (decision and decision.is_preemption and decision.preempted_target_id)
            else "NONE"
        )
        att_telemetry = {
            "old_owner": old_owner,
            "new_owner": new_owner,
            "reason": att_reason,
            "preempted_target": preempted_target,
        }

        # Determine visual target grounding and direct camera lock
        active_target = target_state.active_target
        has_visual_target = bool(
            active_target is not None
            and active_target.modality in (Modality.FUSED, Modality.VISION)
        )

        # Active track resolution: only the track corresponding to active_target
        active_track = None
        if active_target is not None and self._latest_tracks:
            for tr in self._latest_tracks:
                tr_id = getattr(tr, "target_id", getattr(tr, "track_id", None))
                if tr_id == active_target.target_id:
                    active_track = tr
                    break

        active_track_seen = bool(
            active_track is not None
            and getattr(active_track, "missed_frames", 0) == 0
            and getattr(active_track, "tracking_state", getattr(active_track, "state", None))
            in (TrackingState.TRACKING, TrackingState.DETECTED)
        )
        has_visual_lock = bool(has_visual_target and active_track_seen)

        # Invariant: Zero-Coast on Valid Vision. If valid faces are present, resolve live track
        has_valid_faces = any((getattr(f, "confidence", None) or UNSCORED_CONFIDENCE) >= 0.50 for f in faces)
        if (not has_visual_lock) and (has_valid_faces or self._latest_tracks):
            live_tr = next(
                (tr for tr in self._latest_tracks
                 if getattr(tr, "missed_frames", 0) == 0
                 and getattr(tr, "tracking_state", getattr(tr, "state", None)) in (TrackingState.TRACKING, TrackingState.DETECTED)),
                None
            )
            if live_tr is not None:
                active_track = live_tr
                active_track_seen = True
                has_visual_lock = True
                has_visual_target = True
                tr_id = getattr(live_tr, "target_id", getattr(live_tr, "track_id", None))
                matching_cand = next((c for c in target_state.candidate_targets if c.target_id == tr_id), None)
                if matching_cand is not None:
                    active_target = matching_cand


        # Invalidate old coast cache if target dropped or target switched
        if not has_visual_target:
            self._last_visual_target_yaw = None
            self._last_visual_target_id = None
            self._last_visual_seen_time = 0.0
            self._was_visually_tracking = False
        elif self._last_visual_target_id is not None and self._last_visual_target_id != active_target.target_id:
            self._last_visual_target_yaw = None
            self._last_visual_target_id = None
            self._last_visual_seen_time = 0.0
            self._was_visually_tracking = False

        if has_visual_lock:
            self._last_visual_target_yaw = float(active_target.body_azimuth_deg)
            self._last_visual_seen_time = timestamp
            self._last_visual_target_id = active_target.target_id
            self._was_visually_tracking = True

        # Calculate visual target elapsed time
        time_since_visual = (timestamp - self._last_visual_seen_time) if self._last_visual_seen_time > 0.0 else 999.0
        visual_target_age_ms = max(0.0, time_since_visual * 1000.0) if self._last_visual_seen_time > 0.0 else 99999.0

        # Verified human speech and stabilized audio bearing evaluation
        has_verified_speech = bool(speech is not None and speech.is_speech and speech.confidence >= 0.50)
        audio_evidence = bool(self._latest_audio is not None and self._latest_audio.valid)
        audio_bearing = float(self._latest_audio.azimuth_deg) if audio_evidence else 0.0
        audio_bearing_age_ms = max(0.0, (timestamp - self._latest_audio.timestamp) * 1000.0) if audio_evidence else 99999.0
        audio_bearing_valid = bool(
            audio_evidence
            and audio_bearing_age_ms < 600.0
            and not self._latest_audio.is_outlier
            and getattr(self._latest_audio, "variance", 0.0) <= 1.0
        )

        # Single mechanical motor envelope: strictly [-75.0, +75.0]
        is_in_audio_envelope = bool(-75.0 <= audio_bearing <= 75.0)

        # ---------------------------------------------------------------------
        # 5-STATE ATTENTION OWNERSHIP & REACQUISITION MACHINE
        # ---------------------------------------------------------------------
        coast_active = False
        audio_reacq_active = False

        cmd_reason = "NONE"

        if command.priority_source in (
            PrioritySource.EXPLICIT_USER_GAZE,
            PrioritySource.DIRECT_DIALOGUE_INTENT,
            PrioritySource.GESTURE_INTENT,
            PrioritySource.EMERGENCY_STOP,
        ):
            command_source = command.priority_source.value
            target_source = "CAMERA" if has_visual_lock else "NONE"
            cmd_reason = f"PRIORITY_COMMAND_{command_source}"
        elif has_visual_lock:
            # STATE 1: VISUAL_LOCK & STATE 4: VISUAL_HANDOVER
            is_handover = self._audio_reacq_active
            if self._audio_reacq_active:
                # STATE 4: VISUAL_HANDOVER on first valid visual detection
                self._audio_reacq_active = False
                self._audio_reacq_target_yaw = None
                self.visual_handover_count += 1
            command_source = "VISUAL"
            target_source = "CAMERA"
            self.commands_from_visual += 1
            cmd_target_yaw = float(active_target.body_azimuth_deg) if active_target is not None else float(active_track.body_azimuth_deg)
            target_id_val = active_target.target_id if active_target is not None else str(getattr(active_track, "target_id", getattr(active_track, "track_id", "person_1")))
            psource = command.priority_source if command.priority_source in (PrioritySource.ACTIVE_SPEAKER, PrioritySource.DIRECT_DIALOGUE_INTENT) else PrioritySource.VISUAL_TRACKING
            command = replace(
                command,
                target_yaw_deg=cmd_target_yaw,
                priority_source=psource,
                active_target_id=target_id_val,
                gaze_state=GazeStateEnum.TRACKING,
            )
            cmd_reason = f"VISUAL_HANDOVER_TARGET_{target_id_val}" if is_handover else f"VISUAL_LOCK_TARGET_{target_id_val}"
        elif (
            not has_valid_faces
            and has_visual_target
            and active_target is not None
            and self._was_visually_tracking
            and self._last_visual_target_id == active_target.target_id
            and self._last_visual_target_yaw is not None
            and time_since_visual <= self.coast_timeout_s
        ):
            # STATE 2: VISUAL_COAST (0.0 - 1.0s: hold last visual bearing, do not snap to 0.0°, block audio reacq)
            coast_active = True
            command_source = "VISUAL_COAST"
            target_source = "COAST"
            command = replace(
                command,
                target_yaw_deg=float(self._last_visual_target_yaw),
                priority_source=PrioritySource.VISUAL_TRACKING,
                active_target_id=self._last_visual_target_id,
            )
            cmd_reason = f"COASTING_LAST_VISUAL_{self._last_visual_target_id}_AGE_{visual_target_age_ms:.0f}MS"
        elif has_valid_faces and self._latest_tracks:
            # Fallback direct visual recovery to maintain zero-coast invariant on valid vision
            command_source = "VISUAL"
            target_source = "CAMERA"
            self.commands_from_visual += 1
            best_tr = self._latest_tracks[0]
            cmd_target_yaw = float(best_tr.body_azimuth_deg)
            target_id_val = str(getattr(best_tr, "target_id", getattr(best_tr, "track_id", "person_1")))
            command = replace(
                command,
                target_yaw_deg=cmd_target_yaw,
                priority_source=PrioritySource.VISUAL_TRACKING,
                active_target_id=target_id_val,
                gaze_state=GazeStateEnum.TRACKING,
            )
            cmd_reason = f"VISUAL_RECOVERY_TARGET_{target_id_val}"
        elif (
            time_since_visual > self.coast_timeout_s
            and has_verified_speech
            and audio_bearing_valid
            and not is_robot_speaking
            and is_in_audio_envelope
        ):
            # STATE 3: AUDIO_REACQUISITION (strictly within [-75°, +75°], single-episode limited)
            if self._audio_reacq_active:
                # Ongoing episode: target yaw is fixed, do NOT wander with repeated audio samples!
                audio_reacq_active = True
                command_source = "AUDIO_REACQUISITION"
                target_source = "AUDIO_REACQUISITION"
                command = replace(
                    command,
                    target_yaw_deg=float(self._audio_reacq_target_yaw),
                    priority_source=PrioritySource.ACTIVE_SPEAKER,
                    gaze_state=GazeStateEnum.ORIENTING,
                )
                cmd_reason = f"AUDIO_REACQ_ONGOING_ORIENTING_TO_{self._audio_reacq_target_yaw:+.1f}DEG"
            elif not self._speech_in_progress:
                # New verified speech episode starts single-shot reacquisition action
                self._audio_reacq_active = True
                self._audio_reacq_target_yaw = float(audio_bearing)
                self._audio_reacq_start_time = timestamp
                self._speech_in_progress = True
                self.audio_reacquisition_count += 1
                audio_reacq_active = True
                command_source = "AUDIO_REACQUISITION"
                target_source = "AUDIO_REACQUISITION"
                command = replace(
                    command,
                    target_yaw_deg=float(self._audio_reacq_target_yaw),
                    priority_source=PrioritySource.ACTIVE_SPEAKER,
                    gaze_state=GazeStateEnum.ORIENTING,
                )
                cmd_reason = f"AUDIO_REACQ_NEW_ORIENTING_TO_{self._audio_reacq_target_yaw:+.1f}DEG"
            else:
                # Speech episode already generated its one action and is still continuing: stay stationary
                command_source = "SAFETY_ZERO"
                target_source = "NONE"
                command = replace(
                    command,
                    target_yaw_deg=float(self.head_angle_deg),
                    priority_source=PrioritySource.IDLE,
                )
                cmd_reason = "AUDIO_REACQ_EPISODE_EXHAUSTED_HOLD_STATIONARY"
        else:
            # STATE 5: IDLE / STATIONARY (no visual, no coast, no verified speech, or outside envelope)
            if not has_verified_speech:
                self._speech_in_progress = False
                self._audio_reacq_active = False
                self._audio_reacq_target_yaw = None
            command_source = "SAFETY_ZERO"
            target_source = "NONE"
            command = replace(
                command,
                target_yaw_deg=float(self.head_angle_deg),
                priority_source=PrioritySource.IDLE,
            )
            cmd_reason = f"STATIONARY_HOLD_HEAD_AT_{self.head_angle_deg:+.1f}DEG"

        # CRITICAL ACCEPTANCE INVARIANT GUARDS
        if command_source in ("VISUAL_COAST", "VISUAL"):
            if not has_visual_target or target_state.active_target is None or self._last_visual_target_id != active_target.target_id:
                # Under NO_ACTIVE_TARGET / IDLE, VISUAL_COAST or VISUAL commands are strictly forbidden!
                command_source = "SAFETY_ZERO"
                target_source = "NONE"
                command = replace(
                    command,
                    target_yaw_deg=float(self.head_angle_deg),
                    priority_source=PrioritySource.IDLE,
                )
                if not cmd_reason.startswith("STATIONARY") and not cmd_reason.startswith("IDLE"):
                    cmd_reason = f"IDLE_STATIONARY_HOLD_HEAD_AT_{self.head_angle_deg:+.1f}DEG"

        if command_source == "VISUAL":
            target_source = "CAMERA"
        elif command_source == "VISUAL_COAST":
            target_source = "COAST"
        elif command_source in ("IDLE", "SAFETY_ZERO"):
            target_source = "NONE"

        # Architectural invariant: raw audio DOA -> head command MUST BE ZERO
        self.commands_from_audio = 0

        # Head command telemetry computation
        prev_target_yaw = float(self._last_target_yaw_telemetry)
        new_target_yaw = float(command.target_yaw_deg)

        active_target_at_command = str(target_state.active_target.target_id) if target_state.active_target else (str(self._last_visual_target_id) if coast_active else "NONE")
        active_track_at_command = str(getattr(active_track, "target_id", getattr(active_track, "track_id", "NONE"))) if active_track else "NONE"
        command_generation_reason = str(cmd_reason)

        cmd_telemetry = {
            "previous_target_yaw": round(prev_target_yaw, 2),
            "new_target_yaw": round(new_target_yaw, 2),
            "command_source": command_source,
            "target_source": target_source,
            "reason": cmd_reason,
            "active_target_at_command": active_target_at_command,
            "active_track_at_command": active_track_at_command,
            "command_generation_reason": command_generation_reason,
        }
        self._last_target_yaw_telemetry = new_target_yaw

        delta_yaw = abs(angular_diff_deg(prev_target_yaw, new_target_yaw))
        if delta_yaw > 3.0:
            self._print_causal_chain(
                delta_yaw=delta_yaw,
                detections=self._latest_detections_telemetry,
                tm=tm_telemetry,
                att=att_telemetry,
                cmd=cmd_telemetry,
                tracks=self._latest_tracks,
            )

        forensic_payload = {
            "detections": list(self._latest_detections_telemetry),
            "target_manager": tm_telemetry,
            "attention": att_telemetry,
            "command": cmd_telemetry,
            "delta_yaw": round(delta_yaw, 2),
        }
        self.last_forensic_chain = forensic_payload

        trajectory = self.planner.plan_step(
            gaze_cmd=command,
            actual_pos_deg=None if self.head_feedback_missing else self.head_angle_deg,
            timestamp=timestamp,
        )
        if self.head_feedback_missing:
            self.head_angle_deg = float(trajectory.position_deg)
            self.head_velocity_deg_s = float(trajectory.velocity_deg_s)

        return GazeResult(
            target_yaw_deg=float(command.target_yaw_deg),
            gaze_state=command.gaze_state,
            owner=command.priority_source,
            target_id=command.active_target_id,
            confidence=float(command.confidence),
            head_angle_deg=self.head_angle_deg,
            face_bearings_deg=tuple(t.body_azimuth_deg for t in self._latest_tracks),
            target_source=target_source,
            visual_target=has_visual_target,
            audio_evidence=audio_evidence,
            command_source=command_source,
            commands_from_audio=self.commands_from_audio,
            audio_bearing_valid=audio_bearing_valid,
            audio_bearing=round(audio_bearing, 1),
            audio_bearing_age_ms=round(audio_bearing_age_ms, 1),
            visual_target_age_ms=round(visual_target_age_ms, 1),
            coast_active=coast_active,
            audio_reacquisition_active=audio_reacq_active,
            audio_reacquisition_count=self.audio_reacquisition_count,
            visual_handover_count=self.visual_handover_count,
            forensic=forensic_payload,
            active_target_at_command=active_target_at_command,
            active_track_at_command=active_track_at_command,
            command_generation_reason=command_generation_reason,
        )

    @staticmethod
    def _print_causal_chain(
        delta_yaw: float,
        detections: List[dict],
        tm: dict,
        att: dict,
        cmd: dict,
        tracks: Optional[List] = None,
    ) -> str:
        lines = [
            f"[FORENSIC CAUSAL CHAIN] Δyaw={delta_yaw:+.1f}° (>3.0°)",
            "DETECTION → TRACK → TARGET → ATTENTION → COMMAND",
        ]
        # 1. DETECTION
        if detections:
            det_strs = []
            for d in detections:
                det_strs.append(
                    f"frame_id={d['frame_id']} ts={d['timestamp']:.3f} bbox={d['bbox']} "
                    f"bearing={d['bearing']:+.1f}° conf={d['confidence']:.2f} "
                    f"src={d['detector_source']} track_id={d['track_id']} track_state={d['track_state']}"
                )
            lines.append("  DETECTION: " + " | ".join(det_strs))
        else:
            lines.append("  DETECTION: NONE")

        # 2. TRACK
        target_id = tm.get("new_active_target")
        track_info = None
        if tracks:
            for tr in tracks:
                tr_id = getattr(tr, "target_id", getattr(tr, "track_id", None))
                if tr_id == target_id:
                    state_val = getattr(getattr(tr, "tracking_state", getattr(tr, "state", None)), "value", "NONE")
                    bearing_val = getattr(tr, "body_azimuth_deg", 0.0)
                    conf_val = getattr(tr, "confidence", 0.0)
                    track_info = f"track_id={tr_id} state={state_val} bearing={bearing_val:+.1f}° conf={conf_val:.2f}"
                    break
            if not track_info and tracks:
                tr = tracks[0]
                tr_id = getattr(tr, "target_id", getattr(tr, "track_id", "NONE"))
                state_val = getattr(getattr(tr, "tracking_state", getattr(tr, "state", None)), "value", "NONE")
                bearing_val = getattr(tr, "body_azimuth_deg", 0.0)
                conf_val = getattr(tr, "confidence", 0.0)
                track_info = f"track_id={tr_id} state={state_val} bearing={bearing_val:+.1f}° conf={conf_val:.2f}"
        if not track_info:
            track_info = f"track_id={target_id} state=NONE"
        lines.append(f"  TRACK    : {track_info}")

        # 3. TARGET
        lines.append(
            f"  TARGET   : prev={tm['previous_active_target']} -> new={tm['new_active_target']} "
            f"reason={tm['reason']}"
        )

        # 4. ATTENTION
        lines.append(
            f"  ATTENTION: old_owner={att['old_owner']} -> new_owner={att['new_owner']} "
            f"reason={att['reason']} preempted={att['preempted_target']}"
        )

        # 5. COMMAND
        lines.append(
            f"  COMMAND  : prev_yaw={cmd['previous_target_yaw']:+.1f}° -> new_yaw={cmd['new_target_yaw']:+.1f}° "
            f"cmd_src={cmd['command_source']} target_src={cmd['target_source']} reason={cmd['reason']} "
            f"act_target={cmd.get('active_target_at_command', 'NONE')} "
            f"act_track={cmd.get('active_track_at_command', 'NONE')}"
        )
        msg = "\n".join(lines)
        try:
            print(msg)
        except UnicodeEncodeError:
            print(msg.encode("ascii", errors="replace").decode("ascii"))
        return msg

    def _ingest_audio(self, doa_deg: float, timestamp: float, confidence: float,
                      is_robot_speaking: bool = False) -> None:
        observation = self.audio_perception.process_raw_doa(
            raw_doa_deg=float(doa_deg),
            timestamp=timestamp,
            actual_head_yaw_deg=self.head_angle_deg,
            confidence=confidence,
            is_robot_speaking=is_robot_speaking,
        )
        self._latest_audio = self.audio_filter.filter_observation(
            obs=observation, head_velocity_deg_s=self.head_velocity_deg_s
        )

    def _ingest_vision(
        self, faces: Sequence[Detection], frame_size: Tuple[int, int], timestamp: float
    ) -> None:
        width, height = frame_size
        observations = []
        for face in faces:
            observations.append(
                self.visual_perception.process_detection(
                    x=face.x, y=face.y, w=face.w, h=face.h,
                    depth_m=self._estimate_distance(face.w, width),
                    timestamp=timestamp,
                    actual_head_yaw_deg=self.head_angle_deg,
                    frame_width=width, frame_height=height,
                    confidence=face.confidence if face.confidence is not None else UNSCORED_CONFIDENCE,
                )
            )
        self._latest_tracks = self.visual_tracker.update(
            observations=observations,
            timestamp=timestamp,
            actual_head_yaw_deg=self.head_angle_deg,
        )

        self._latest_detections_telemetry = []
        for face_idx, (face, obs) in enumerate(zip(faces, observations)):
            tid = self.visual_tracker.last_associations.get(face_idx, "NONE")
            t_state = "NONE"
            if tid != "NONE" and tid in self.visual_tracker.tracks:
                t_state = self.visual_tracker.tracks[tid].state.value
            det_telem = {
                "frame_id": self._frame_index,
                "timestamp": round(float(timestamp), 3),
                "bbox": [int(face.x), int(face.y), int(face.w), int(face.h)],
                "bearing": round(float(obs.body_azimuth_deg), 1),
                "confidence": round(float(face.confidence if face.confidence is not None else UNSCORED_CONFIDENCE), 2),
                "detector_source": str(face.detector_source or "UNKNOWN"),
                "track_id": str(tid),
                "track_state": str(t_state),
            }
            self._latest_detections_telemetry.append(det_telem)

    @staticmethod
    def _estimate_distance(box_width_px: int, frame_width_px: int) -> float:
        if box_width_px <= 0:
            return 1.5
        focal_px = frame_width_px * 0.8
        return float(min(4.0, max(0.3, (0.16 * focal_px) / box_width_px)))
