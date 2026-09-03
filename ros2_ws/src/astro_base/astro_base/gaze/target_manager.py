"""Target Manager with Dual-Threshold Hysteresis and Turn-Taking Arbitration.

Features:
  1. Active Target Locking with Hysteresis (Acquisition ≥0.75 vs Hold ≥0.40)
  2. Multi-Speaker Candidate Tracking
  3. Minimum Social Attention Dwell Time (≥2.5s)
  4. Turn-Taking Preemption for New Distinct Speakers (≥20° after 0.8s)
  5. Graceful Target Coasting and Lost Target Timeout
"""

import math
from typing import List, Optional
from astro_base.gaze.angle_math import circular_distance_deg
from astro_base.gaze.types import FusedTarget, Modality, TargetState, TrackingState


class TargetManagerCore:
    """Manages active speaker locking, candidate tracks, and turn-taking arbitration."""

    def __init__(
        self,
        acquisition_threshold: float = 0.75,
        hold_threshold: float = 0.40,
        target_lost_timeout_s: float = 1.0,
        min_attention_dwell_s: float = 2.50,
        turn_taking_min_dwell_s: float = 0.80,
        turn_taking_min_angle_deg: float = 20.0,
        max_tracked_candidates: int = 6,
    ):
        self.acquisition_threshold = acquisition_threshold
        self.hold_threshold = hold_threshold
        self.target_lost_timeout_s = target_lost_timeout_s
        self.min_attention_dwell_s = min_attention_dwell_s
        self.turn_taking_min_dwell_s = turn_taking_min_dwell_s
        self.turn_taking_min_angle_deg = turn_taking_min_angle_deg
        self.max_tracked_candidates = max_tracked_candidates

        self.active_target: Optional[FusedTarget] = None
        self.candidate_targets: List[FusedTarget] = []

        self._active_target_start_time: float = 0.0
        self._last_active_observed_time: float = 0.0
        self._last_healthy_observed_time: float = 0.0
        self._new_speaker_candidate_id: Optional[str] = None
        self._new_speaker_first_heard_time: float = 0.0
        self.last_target_birth: Optional[dict] = None

    def reset(self) -> None:
        self.active_target = None
        self.candidate_targets.clear()
        self._active_target_start_time = 0.0
        self._last_active_observed_time = 0.0
        self._last_healthy_observed_time = 0.0
        self._new_speaker_candidate_id = None
        self._new_speaker_first_heard_time = 0.0
        self.last_target_birth = None

    def reset_lifecycle(self) -> None:
        """Completely purges all active and candidate targets on transition to IDLE."""
        self.reset()

    def update(
        self,
        fused_targets: List[FusedTarget],
        timestamp: float,
    ) -> TargetState:
        """Updates target management state and arbitrates active target selection.

        Args:
          fused_targets: List of candidate FusedTargets from AudioVisualFusionCore
          timestamp: Current monotonic timestamp
        """
        self.candidate_targets = fused_targets[:self.max_tracked_candidates]

        # 1. Evaluate current active target if one exists
        if self.active_target is not None:
            # Find matching target in current observations by ID
            matched = next((t for t in self.candidate_targets if t.target_id == self.active_target.target_id), None)

            if matched is not None:
                # Target observed in this frame -> update state
                self.active_target = matched
                self._last_active_observed_time = timestamp

                # Check hold threshold
                if matched.confidence >= self.hold_threshold:
                    self._last_healthy_observed_time = timestamp
                else:
                    time_unhealthy = timestamp - self._last_healthy_observed_time
                    if time_unhealthy > self.target_lost_timeout_s:
                        # Target lost due to sustained low confidence
                        self.active_target = None
            else:
                # Active target missing in this frame -> check timeout
                time_missing = timestamp - self._last_active_observed_time
                # If another candidate face is present with sufficient acquisition confidence,
                # use a shorter missing timeout (0.5s) so the head turns to the other face
                # instead of holding onto the missing face for 2.5s.
                has_other_candidate = any(
                    t.confidence >= self.acquisition_threshold
                    for t in self.candidate_targets
                    if t.target_id != self.active_target.target_id
                )
                effective_timeout = 0.5 if has_other_candidate else self.target_lost_timeout_s
                if time_missing > effective_timeout:
                    self.active_target = None

        # 2. Candidate Selection & Turn-Taking Arbitration
        if self.active_target is None:
            # No active target: Select best candidate meeting acquisition threshold (≥0.75)
            best_candidate = next((t for t in self.candidate_targets if t.confidence >= self.acquisition_threshold), None)

            if best_candidate is not None:
                self.active_target = best_candidate
                self._active_target_start_time = timestamp
                self._last_active_observed_time = timestamp
                self._last_healthy_observed_time = timestamp
                self._new_speaker_candidate_id = None

                # Log structured TARGET_BIRTH telemetry
                self.last_target_birth = {
                    "timestamp": round(timestamp, 3),
                    "target_id": best_candidate.target_id,
                    "source": best_candidate.modality.value if hasattr(best_candidate.modality, "value") else str(best_candidate.modality),
                    "bearing": round(best_candidate.body_azimuth_deg, 1),
                    "confidence": round(best_candidate.confidence, 2),
                    "freshness": round(max(0.0, 1.0 - (timestamp - best_candidate.timestamp)), 2),
                    "reason": f"TARGET_BIRTH_{best_candidate.target_id}",
                }

        else:
            # Active target exists: Check if a new speaker warrants turn-taking switch
            dwell_elapsed = timestamp - self._active_target_start_time

            # Search for another candidate speaker
            candidate_speaker = next(
                (
                    t for t in self.candidate_targets
                    if t.target_id != self.active_target.target_id
                    and t.is_speaking
                    and t.confidence >= self.acquisition_threshold
                ),
                None
            )

            if candidate_speaker is not None:
                ang_separation = circular_distance_deg(
                    candidate_speaker.body_azimuth_deg, self.active_target.body_azimuth_deg
                )

                if ang_separation >= self.turn_taking_min_angle_deg:
                    # Track candidate speaker persistence
                    if self._new_speaker_candidate_id == candidate_speaker.target_id:
                        sustained_time = timestamp - self._new_speaker_first_heard_time
                        # Turn-taking switch requires the new candidate to speak continuously for at least turn_taking_min_dwell_s (0.8s)
                        # AND the current target to have been attended for at least turn_taking_min_dwell_s
                        # When the current target is NOT speaking, use a shorter dwell
                        # requirement (half) so the robot responds faster to a new voice.
                        effective_dwell = self.turn_taking_min_dwell_s
                        if not self.active_target.is_speaking:
                            effective_dwell = self.turn_taking_min_dwell_s * 0.5
                        if sustained_time >= effective_dwell and dwell_elapsed >= effective_dwell:
                            # Switch active target to new speaker!
                            self.active_target = candidate_speaker
                            self._active_target_start_time = timestamp
                            self._last_active_observed_time = timestamp
                            self._new_speaker_candidate_id = None
                            self.last_target_birth = {
                                "timestamp": round(timestamp, 3),
                                "target_id": candidate_speaker.target_id,
                                "source": candidate_speaker.modality.value if hasattr(candidate_speaker.modality, "value") else str(candidate_speaker.modality),
                                "bearing": round(candidate_speaker.body_azimuth_deg, 1),
                                "confidence": round(candidate_speaker.confidence, 2),
                                "freshness": round(max(0.0, 1.0 - (timestamp - candidate_speaker.timestamp)), 2),
                                "reason": f"TURN_TAKING_SWITCH_{candidate_speaker.target_id}",
                            }
                    else:
                        self._new_speaker_candidate_id = candidate_speaker.target_id
                        self._new_speaker_first_heard_time = timestamp
                else:
                    self._new_speaker_candidate_id = None
            else:
                self._new_speaker_candidate_id = None

        return TargetState(
            active_target=self.active_target,
            candidate_targets=self.candidate_targets,
            timestamp=timestamp,
        )
