"""ASTRO V1 — Behavioral Intelligence Engine (Phase 7).

Pure Python, deterministic, local behavioral decision engine.
Answers: "How should ASTRO behave in this situation?" by synthesizing:
  - World Model (people, objects, spatial conflicts, acoustic candidates)
  - Self State & Self Model (operational state, capabilities, focused person)
  - Active Goal (SAFETY, SOCIAL, TASK, MAINTENANCE)
  - Metacognitive State & Cognitive Decision (CONTINUE, SEEK_INFORMATION, REASSESS)
  - Affective Modulators (arousal, urgency, frustration, curiosity)
  - Social Phase (UNATTENDED, NOTICE_PERSON, ORIENTING, GREETING, ENGAGED, etc.)

STRICT ARCHITECTURAL INVARIANTS:
  1. DETERMINISTIC & LOCAL: Zero LLMs, zero network calls, zero blocking I/O.
  2. NO MOTOR CONTROL: Emits BehavioralIntent, NOT direct motor or servo commands.
  3. SAFETY NON-BYPASS: Hard safety and physical validation remain exclusively in ActionManager.
  4. ANTI-FLAPPING: Uses hysteresis and minimum dwell time to eliminate behavioral chattering.
"""

from __future__ import annotations

from collections import deque
import logging
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from astro_ai.brain.world_model import WorldModel
from astro_ai.contracts.behavior_types import (
    BehavioralIntent,
    BehaviorPriority,
    BehaviorStatus,
    BehaviorType,
)
from astro_ai.contracts.consciousness_types import (
    CognitiveDecision,
    CognitiveDecisionType,
    Goal,
    InformationSufficiency,
    RobotAffectiveState,
    SelfState,
)
from astro_ai.contracts.person_state import UnifiedPersonState
from astro_ai.state_machine import RobotState

_LOG = logging.getLogger(__name__)


class BehaviorEngine:
    """Thread-safe engine for deterministic behavioral selection and lifecycle control."""

    def __init__(
        self,
        min_dwell_time_s: float = 1.0,
        history_size: int = 50,
    ):
        self._lock = threading.RLock()
        self.min_dwell_time_s: float = max(0.2, float(min_dwell_time_s))

        # Active state
        self._active_behavior: Optional[BehavioralIntent] = None
        self._behavior_history: deque[BehavioralIntent] = deque(maxlen=max(10, int(history_size)))

        # Hysteresis state trackers
        self._is_approaching: bool = False
        self._is_retreating: bool = False

        # Speech & attentive listening tracking
        self._user_speech_start_ts: float = 0.0
        self._last_attentive_nod_ts: float = 0.0
        self._was_user_speaking: bool = False

    @property
    def active_behavior(self) -> Optional[BehavioralIntent]:
        """Returns the currently active BehavioralIntent if any."""
        with self._lock:
            return self._active_behavior

    def get_behavior_history(self) -> List[BehavioralIntent]:
        """Returns a snapshot of recently completed/interrupted behaviors."""
        with self._lock:
            return list(self._behavior_history)

    def reset(self) -> None:
        """Resets active behavior and internal state."""
        with self._lock:
            if self._active_behavior and self._active_behavior.status == BehaviorStatus.ACTIVE:
                self._active_behavior.mark_cancelled("engine_reset")
                self._behavior_history.append(self._active_behavior)
            self._active_behavior = None
            self._is_approaching = False
            self._is_retreating = False
            self._user_speech_start_ts = 0.0
            self._last_attentive_nod_ts = 0.0
            self._was_user_speaking = False

    def step(
        self,
        world_model: WorldModel,
        self_state: SelfState,
        active_goal: Optional[Goal] = None,
        cognitive_decision: Optional[CognitiveDecision] = None,
        affective_state: Optional[RobotAffectiveState] = None,
        social_phase: Optional[str] = None,
        now: Optional[float] = None,
    ) -> BehavioralIntent:
        """Evaluates situational intelligence to select and manage BehavioralIntent.

        Returns:
            The authoritative active BehavioralIntent.
        """
        ts = time.time() if now is None else float(now)

        with self._lock:
            # 1. Update continuous speech observation
            is_user_speaking = self._check_user_speaking(world_model, self_state)
            if is_user_speaking:
                if not self._was_user_speaking:
                    self._user_speech_start_ts = ts
            else:
                self._user_speech_start_ts = 0.0
            self._was_user_speaking = is_user_speaking

            # 2. Check completion / failure of currently active behavior
            self._evaluate_active_behavior_lifecycle(world_model, self_state, ts)

            # 3. Formulate candidate behaviors
            candidates = self._generate_candidates(
                world_model=world_model,
                self_state=self_state,
                active_goal=active_goal,
                cognitive_decision=cognitive_decision,
                affective_state=affective_state,
                social_phase=social_phase,
                is_user_speaking=is_user_speaking,
                now=ts,
            )

            # 4. Arbitrate among candidates
            selected = self._arbitrate(candidates, affective_state=affective_state, now=ts)
            return selected

    # -------------------------------------------------------------------------
    # Candidate Generation
    # -------------------------------------------------------------------------

    def _generate_candidates(
        self,
        world_model: WorldModel,
        self_state: SelfState,
        active_goal: Optional[Goal],
        cognitive_decision: Optional[CognitiveDecision],
        affective_state: Optional[RobotAffectiveState],
        social_phase: Optional[str],
        is_user_speaking: bool,
        now: float,
    ) -> List[BehavioralIntent]:
        """Generates candidate behaviors from sensory, cognitive, and social context."""
        candidates: List[BehavioralIntent] = []
        op_state = self_state.operational_state

        # ---------------------------------------------------------------------
        # 1. Critical Safety Candidate
        # ---------------------------------------------------------------------
        front_clearance = float(world_model._environment.get("front_clearance_m", 5.0))
        is_obstacle_near = bool(world_model._environment.get("is_obstacle_near", False))
        if front_clearance < 0.50 or is_obstacle_near:
            candidates.append(
                BehavioralIntent(
                    behavior_type=BehaviorType.SAFETY_HALT,
                    priority=BehaviorPriority.CRITICAL_SAFETY,
                    reason=f"obstacle_proximity: front_clearance={front_clearance:.2f}m",
                    parameters={"front_clearance_m": front_clearance},
                    timeout_s=2.0,
                    created_at=now,
                )
            )

        # ---------------------------------------------------------------------
        # 2. Active Social Engagement Candidates
        # ---------------------------------------------------------------------
        # (a) Attentive Listening nod during sustained user speech
        if is_user_speaking and self._user_speech_start_ts > 0.0:
            speech_dur = now - self._user_speech_start_ts
            time_since_last_nod = now - self._last_attentive_nod_ts
            if speech_dur >= 2.5 and time_since_last_nod >= 3.5:
                candidates.append(
                    BehavioralIntent(
                        behavior_type=BehaviorType.ATTENTIVE_LISTENING,
                        priority=BehaviorPriority.ACTIVE_ENGAGEMENT,
                        reason=f"sustained_speech_attentive_cue: dur={speech_dur:.1f}s",
                        parameters={"duration_ms": 600},
                        timeout_s=1.0,
                        created_at=now,
                    )
                )

        # (b) Thinking Gaze Aversion when ASTRO is computing response
        is_thinking = (
            op_state in (RobotState.THINKING, RobotState.THINKING_ACK)
            or bool(world_model._robot_state.get("is_thinking", False))
        )
        if is_thinking:
            candidates.append(
                BehavioralIntent(
                    behavior_type=BehaviorType.THINKING_AVERSION,
                    priority=BehaviorPriority.ACTIVE_ENGAGEMENT,
                    reason="thinking_cognitive_gaze_aversion",
                    parameters={"offset_yaw_deg": 3.0},
                    timeout_s=4.0,
                    created_at=now,
                )
            )

        # (c) Active Dialogue Gaze Maintenance when speaking
        is_robot_speaking = (
            self_state.is_speaking
            or op_state == RobotState.SPEAKING
            or bool(world_model._robot_state.get("is_speaking", False))
        )
        if is_robot_speaking:
            focused_pid = self_state.focused_person_id
            if not focused_pid:
                if world_model._active_speaker:
                    focused_pid = world_model._active_speaker.person_id
                else:
                    present_p = [p for p in world_model._people.values() if p.is_present]
                    focused_pid = present_p[0].person_id if present_p else None
            target_p = world_model._people.get(focused_pid) if focused_pid else None
            candidates.append(
                BehavioralIntent(
                    behavior_type=BehaviorType.ACTIVE_SOCIAL_ENGAGEMENT,
                    priority=BehaviorPriority.ACTIVE_ENGAGEMENT,
                    target_id=focused_pid,
                    reason="speaking_active_dialogue_engagement",
                    parameters={"target_yaw_deg": target_p.azimuth_deg if target_p else 0.0},
                    timeout_s=5.0,
                    created_at=now,
                )
            )

        # ---------------------------------------------------------------------
        # 3. Active Perception Candidates
        # ---------------------------------------------------------------------
        world_conflicts = world_model.detect_conflicts()
        has_attention_split = any(c.get("type") == "SPATIAL_ATTENTION_SPLIT" for c in world_conflicts)

        if (
            cognitive_decision
            and cognitive_decision.decision_type == CognitiveDecisionType.SEEK_INFORMATION
            and cognitive_decision.metadata.get("stimulus_type") == "AUDIO"
        ):
            target_yaw = float(cognitive_decision.metadata.get("target_yaw_deg", 0.0))
            cand_entity_id = cognitive_decision.metadata.get("entity_id")

            # If there's an attention split with an actively engaged partner, do NOT rashly jump away
            if has_attention_split and self_state.focused_person_id:
                # Issue puzzled tilt rather than blind jump
                candidates.append(
                    BehavioralIntent(
                        behavior_type=BehaviorType.PUZZLED_TILT,
                        priority=BehaviorPriority.CONFUSION_RECOVERY,
                        reason="spatial_attention_split_conflicting_audio",
                        parameters={"conflicting_yaw_deg": target_yaw},
                        timeout_s=1.5,
                        created_at=now,
                    )
                )
            else:
                candidates.append(
                    BehavioralIntent(
                        behavior_type=BehaviorType.ACTIVE_PERCEPTION_SEARCH,
                        priority=BehaviorPriority.ACTIVE_PERCEPTION,
                        target_id=str(cand_entity_id) if cand_entity_id else None,
                        reason="metacognitive_seek_information_acoustic",
                        parameters={
                            "target_yaw_deg": target_yaw,
                            "azimuth_deg": target_yaw,
                            "confidence": 0.85,
                        },
                        related_prediction_id="EXPECT_FACE_AFTER_HEAD_ATTENTION",
                        source_decision_id=cognitive_decision.decision_id,
                        timeout_s=2.5,
                        created_at=now,
                    )
                )

        # ---------------------------------------------------------------------
        # 4. Social Regulation & Proxemics Candidates
        # ---------------------------------------------------------------------
        focused_person = self._get_interlocutor(world_model, self_state)
        if focused_person and focused_person.is_present:
            p_dist = focused_person.distance_m
            p_yaw = focused_person.azimuth_deg

            # (a) Proxemics Retreat (person stepped too close)
            # Hysteresis: trigger at < 0.7m, stop at >= 1.0m
            # HRI Guard: Do not roll backward if user is seated (e.g. at desk/table) or mobile retreat disabled
            p_activity = str(getattr(focused_person, "current_activity", "") or "").upper()
            is_seated = "SITTING" in p_activity or "SEATED" in p_activity
            can_retreat = getattr(self, "enable_mobile_retreat", True) and not is_seated

            if self._is_retreating:
                if p_dist < 1.00 and can_retreat:
                    candidates.append(
                        BehavioralIntent(
                            behavior_type=BehaviorType.MAINTAIN_SOCIAL_DISTANCE,
                            priority=BehaviorPriority.SOCIAL_REGULATION,
                            target_id=focused_person.person_id,
                            reason=f"retreat_hysteresis_active: dist={p_dist:.2f}m",
                            parameters={"speed": 0.15, "direction": "backward", "distance_m": p_dist},
                            timeout_s=2.0,
                            created_at=now,
                        )
                    )
                else:
                    self._is_retreating = False
            elif p_dist < 0.70 and can_retreat:
                self._is_retreating = True
                candidates.append(
                    BehavioralIntent(
                        behavior_type=BehaviorType.MAINTAIN_SOCIAL_DISTANCE,
                        priority=BehaviorPriority.SOCIAL_REGULATION,
                        target_id=focused_person.person_id,
                        reason=f"proxemics_too_close: dist={p_dist:.2f}m < 0.70m",
                        parameters={"speed": 0.15, "direction": "backward", "distance_m": p_dist},
                        timeout_s=2.0,
                        created_at=now,
                    )
                )

            # (b) Approach Interlocutor (person is far, path is clear, goal permits)
            # Hysteresis: trigger at > 2.5m, stop at <= 1.8m
            goal_type = active_goal.goal_type.value if active_goal else "SOCIAL"
            can_approach = (goal_type in ("SOCIAL", "TASK") and front_clearance > 1.2 and not self._is_retreating)

            if self._is_approaching:
                if p_dist > 1.80 and can_approach:
                    candidates.append(
                        BehavioralIntent(
                            behavior_type=BehaviorType.APPROACH_INTERLOCUTOR,
                            priority=BehaviorPriority.SOCIAL_REGULATION,
                            target_id=focused_person.person_id,
                            reason=f"approach_hysteresis_active: dist={p_dist:.2f}m",
                            parameters={"speed": 0.20, "direction": "forward", "distance_m": p_dist},
                            timeout_s=3.0,
                            created_at=now,
                        )
                    )
                else:
                    self._is_approaching = False
            elif p_dist > 2.50 and can_approach and front_clearance > 1.80:
                self._is_approaching = True
                candidates.append(
                    BehavioralIntent(
                        behavior_type=BehaviorType.APPROACH_INTERLOCUTOR,
                        priority=BehaviorPriority.SOCIAL_REGULATION,
                        target_id=focused_person.person_id,
                        reason=f"interlocutor_distant_approach: dist={p_dist:.2f}m > 2.50m",
                        parameters={"speed": 0.20, "direction": "forward", "distance_m": p_dist},
                        timeout_s=3.0,
                        created_at=now,
                    )
                )

            # (c) Head Yaw Alignment / Centering
            # ALIGN_BODY_TO_TARGET can ONLY be triggered if:
            # 1. Target angle is verified in true body frame (head encoder is valid and known, NOT unknown/estimated)
            # 2. Head target is mechanically unreachable (abs(p_yaw) > 75.0)
            # 3. Visual target is stable (is_present, high visual confidence or eye contact, not stale)
            # 4. Not an audio-only or stale target
            is_encoder_verified = (
                getattr(focused_person, "body_yaw_source", None) == "ENCODER"
                or getattr(self_state, "head_position_source", None) == "ENCODER"
                or getattr(self_state, "is_head_encoder_valid", False)
            )
            is_mechanically_unreachable = abs(p_yaw) > 75.0
            is_visual_stable = (
                focused_person.is_present
                and (focused_person.visual_confidence >= 0.40 or getattr(focused_person, "is_looking_at_robot", False))
                and not getattr(focused_person, "is_audio_only", False)
            )

            if (
                is_encoder_verified
                and is_mechanically_unreachable
                and is_visual_stable
                and not self._is_approaching
                and not self._is_retreating
            ):
                candidates.append(
                    BehavioralIntent(
                        behavior_type=BehaviorType.ALIGN_BODY_TO_TARGET,
                        priority=BehaviorPriority.INTERACTION_INITIATION + 0.05,
                        target_id=focused_person.person_id,
                        reason=f"head_yaw_limit_align_body: yaw={p_yaw:.1f}deg > 75deg (encoder_verified)",
                        parameters={"target_yaw_deg": p_yaw},
                        timeout_s=1.5,
                        created_at=now,
                    )
                )

            # (d) Maintain Gaze in comfortable zone
            if 0.80 <= p_dist <= 2.50 and not self._is_approaching and not self._is_retreating:
                candidates.append(
                    BehavioralIntent(
                        behavior_type=BehaviorType.MAINTAIN_GAZE,
                        priority=BehaviorPriority.GAZE_TRACKING,
                        target_id=focused_person.person_id,
                        reason="interlocutor_in_comfort_zone_maintain_gaze",
                        parameters={"target_yaw_deg": p_yaw, "azimuth_deg": p_yaw},
                        timeout_s=4.0,
                        created_at=now,
                    )
                )

        # ---------------------------------------------------------------------
        # 5. Interaction Initiation Candidates (Person Appeared)
        # ---------------------------------------------------------------------
        unfocused_people = [
            p for p in world_model._people.values()
            if p.is_present and (focused_person is None or p.person_id != focused_person.person_id)
        ]
        if unfocused_people and not focused_person:
            closest = min(unfocused_people, key=lambda p: p.distance_m)
            candidates.append(
                BehavioralIntent(
                    behavior_type=BehaviorType.ORIENT_TO_STIMULUS,
                    priority=BehaviorPriority.INTERACTION_INITIATION,
                    target_id=closest.person_id,
                    reason=f"person_detected_orient: pid={closest.person_id}",
                    parameters={"target_yaw_deg": closest.azimuth_deg, "azimuth_deg": closest.azimuth_deg},
                    timeout_s=2.0,
                    created_at=now,
                )
            )

        # ---------------------------------------------------------------------
        # 6. Confusion Recovery Candidates (Metacognitive Conflict / Reassess)
        # ---------------------------------------------------------------------
        if (
            cognitive_decision
            and cognitive_decision.decision_type in (
                CognitiveDecisionType.REASSESS,
                CognitiveDecisionType.REVIEW_STRATEGY,
            )
        ):
            candidates.append(
                BehavioralIntent(
                    behavior_type=BehaviorType.PUZZLED_TILT,
                    priority=BehaviorPriority.CONFUSION_RECOVERY,
                    reason=f"metacognitive_reassessment_recovery: {cognitive_decision.reason}",
                    parameters={"duration_ms": 600},
                    timeout_s=1.5,
                    created_at=now,
                )
            )

        # ---------------------------------------------------------------------
        # 7. Baseline Idle Candidate
        # ---------------------------------------------------------------------
        candidates.append(
            BehavioralIntent(
                behavior_type=BehaviorType.IDLE_ATTENTIVE,
                priority=BehaviorPriority.IDLE,
                reason="baseline_quiescent_state",
                timeout_s=10.0,
                created_at=now,
            )
        )

        return candidates

    # -------------------------------------------------------------------------
    # Arbitration & Preemption
    # -------------------------------------------------------------------------

    def _arbitrate(
        self,
        candidates: List[BehavioralIntent],
        affective_state: Optional[RobotAffectiveState],
        now: float,
    ) -> BehavioralIntent:
        """Deterministically selects and manages the winning behavior."""
        if not candidates:
            return BehavioralIntent(behavior_type=BehaviorType.IDLE_ATTENTIVE, priority=0.1, created_at=now)

        # Sort strictly descending by priority
        candidates.sort(key=lambda b: b.priority, reverse=True)
        best_candidate = candidates[0]

        # Calculate dynamic minimum dwell time modulated by affective urgency
        effective_dwell = self.min_dwell_time_s
        if affective_state and affective_state.urgency > 0.70:
            effective_dwell = max(0.2, self.min_dwell_time_s * 0.5)

        # Case 1: No active behavior -> immediately activate best candidate
        if self._active_behavior is None or self._active_behavior.status != BehaviorStatus.ACTIVE:
            self._activate_behavior(best_candidate, now)
            return self._active_behavior

        current = self._active_behavior

        # Case 2: Best candidate has strictly higher priority -> immediate preemption!
        if best_candidate.priority > current.priority:
            current.mark_interrupted(f"preempted_by_{best_candidate.behavior_type.value}", now)
            self._behavior_history.append(current)
            self._activate_behavior(best_candidate, now)
            return self._active_behavior

        # Case 3: Same behavior type -> refresh/update parameters without breaking dwell
        if best_candidate.behavior_type == current.behavior_type:
            current.parameters.update(best_candidate.parameters)
            if best_candidate.target_id:
                current.target_id = best_candidate.target_id
            return current

        # Case 4: Lower or equal priority candidate -> respect dwell time (anti-flapping)
        active_dur = now - (current.started_at or current.created_at)
        if active_dur >= effective_dwell:
            current.mark_completed("dwell_satisfied_transition", now)
            self._behavior_history.append(current)
            self._activate_behavior(best_candidate, now)
            return self._active_behavior
        else:
            # Maintain active behavior during dwell interval
            return current

    def _activate_behavior(self, intent: BehavioralIntent, now: float) -> None:
        """Activates a behavior intent and updates internal tracking."""
        intent.mark_active(now)
        self._active_behavior = intent
        if intent.behavior_type == BehaviorType.ATTENTIVE_LISTENING:
            self._last_attentive_nod_ts = now
        _LOG.debug(f"[BehaviorEngine] Activated behavior: {intent.behavior_type.value} (p={intent.priority:.2f})")

    # -------------------------------------------------------------------------
    # Lifecycle & Verification
    # -------------------------------------------------------------------------

    def _evaluate_active_behavior_lifecycle(
        self, world_model: WorldModel, self_state: SelfState, now: float
    ) -> None:
        """Verifies whether the active behavior has completed, failed, or expired."""
        if not self._active_behavior or self._active_behavior.status != BehaviorStatus.ACTIVE:
            return

        current = self._active_behavior

        # 1. Timeout Expiration Check
        if current.is_expired(now):
            current.mark_failed("timeout_expired", now)
            self._behavior_history.append(current)
            self._active_behavior = None
            return

        btype = current.behavior_type

        # 2. Specific Completion Conditions
        if btype == BehaviorType.ACTIVE_PERCEPTION_SEARCH:
            # Completed if visual face detected for target or in view
            has_face = any(
                p.is_present and getattr(p, "has_vision", False)
                for p in world_model._people.values()
            )
            if has_face:
                current.mark_completed("face_verified_by_vision", now)
                self._behavior_history.append(current)
                self._active_behavior = None
                return

        elif btype == BehaviorType.APPROACH_INTERLOCUTOR:
            # Completed if reached personal interaction distance (<= 1.8m)
            interlocutor = self._get_interlocutor(world_model, self_state)
            if interlocutor and interlocutor.distance_m <= 1.80:
                current.mark_completed("reached_interaction_distance", now)
                self._behavior_history.append(current)
                self._is_approaching = False
                self._active_behavior = None
                return

        elif btype == BehaviorType.MAINTAIN_SOCIAL_DISTANCE:
            # Completed if comfortable distance restored (>= 1.0m)
            interlocutor = self._get_interlocutor(world_model, self_state)
            if interlocutor and interlocutor.distance_m >= 1.00:
                current.mark_completed("restored_social_distance", now)
                self._behavior_history.append(current)
                self._is_retreating = False
                self._active_behavior = None
                return

        elif btype in (BehaviorType.ATTENTIVE_LISTENING, BehaviorType.PUZZLED_TILT):
            # Gestures complete after short execution duration (0.7s)
            active_dur = now - (current.started_at or current.created_at)
            if active_dur >= 0.70:
                current.mark_completed("gesture_cycle_completed", now)
                self._behavior_history.append(current)
                self._active_behavior = None
                return

    # -------------------------------------------------------------------------
    # Helper Inspection Utilities
    # -------------------------------------------------------------------------

    def _check_user_speaking(self, world_model: WorldModel, self_state: SelfState) -> bool:
        """Determines whether a user is actively speaking."""
        if self_state.is_listening:
            return True
        if world_model._active_speaker is not None:
            return True
        for p in world_model._people.values():
            if p.is_present and p.is_speaking:
                return True
        return False

    def _get_interlocutor(
        self, world_model: WorldModel, self_state: SelfState
    ) -> Optional[UnifiedPersonState]:
        """Resolves the primary focused interlocutor if established."""
        focused_pid = self_state.focused_person_id
        if focused_pid and focused_pid in world_model._people:
            p = world_model._people[focused_pid]
            if p.is_present:
                return p

        return None
