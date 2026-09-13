"""ASTRO V1 — Robot Affective State and Behavioral Modulator Management.

Governs ASTRO's internal numerical behavioral modulators:
  - arousal: Alertness and sensory receptivity (baseline 0.2, range [0.0, 1.0])
  - urgency: Temporal pressure and safety prioritization (baseline 0.0, range [0.0, 1.0])
  - social_engagement: Receptivity to dialogue and eye contact (baseline 0.0, range [0.0, 1.0])
  - confidence: Epistemic self-assurance (baseline 0.7, range [0.1, 1.0])
  - uncertainty: Ambiguity / lack of information (baseline 0.3, range [0.0, 1.0])
  - curiosity: Information-seeking and novelty orientation (baseline 0.3, range [0.0, 1.0])
  - frustration: Accumulator of action/prediction failures (baseline 0.0, range [0.0, 1.0])

ARCHITECTURAL INVARIANTS:
  1. STRICTLY NON-BLOCKING: All update and decay routines execute in O(1) CPU time.
  2. NO BIOLOGICAL DRIVES: These are numerical behavioral modulators, NOT biological emotions.
  3. NO DIRECT ACTION EMISSION: AffectiveState and AffectiveStateManager CANNOT directly issue
     motor commands, create ActionIntents, or unilaterally mutate the StateMachine.
  4. EMOTION SEPARATION: Does NOT replace or conflict with user emotion detection in EmotionEngine.
"""

from __future__ import annotations

import logging
import math
import threading
from typing import Any, Dict, List, Optional

from astro_ai.contracts.consciousness_types import (
    CognitiveEvent,
    CognitiveEventType,
    RobotAffectiveState,
)

_LOG = logging.getLogger(__name__)


class AffectiveStateManager:
    """Thread-safe manager for ASTRO's dynamic behavioral modulators."""

    # Baseline equilibria
    BASELINE_AROUSAL = 0.2
    BASELINE_URGENCY = 0.0
    BASELINE_SOCIAL = 0.0
    BASELINE_CONFIDENCE = 0.7
    BASELINE_UNCERTAINTY = 0.3
    BASELINE_CURIOSITY = 0.3
    BASELINE_FRUSTRATION = 0.0

    # Bounds
    CONFIDENCE_MIN = 0.1
    CONFIDENCE_MAX = 1.0
    UNCERTAINTY_MIN = 0.0
    UNCERTAINTY_MAX = 1.0

    # Per-step (nominal 0.1s) decay rates towards baselines
    DECAY_RATE_AROUSAL = 0.05
    DECAY_RATE_URGENCY = 0.10
    DECAY_RATE_SOCIAL = 0.05
    DECAY_RATE_CONFIDENCE = 0.02
    DECAY_RATE_UNCERTAINTY = 0.02
    DECAY_RATE_CURIOSITY = 0.03
    DECAY_RATE_FRUSTRATION = 0.05

    def __init__(self, initial_state: Optional[RobotAffectiveState] = None):
        self._lock = threading.RLock()
        self._state = (
            initial_state
            if initial_state is not None
            else RobotAffectiveState()
        )
        self._clamp_locked()

    @property
    def state(self) -> RobotAffectiveState:
        with self._lock:
            return self._state

    def reset(self) -> None:
        """Resets all modulators to their canonical baseline values."""
        with self._lock:
            self._state.arousal = self.BASELINE_AROUSAL
            self._state.urgency = self.BASELINE_URGENCY
            self._state.social_engagement = self.BASELINE_SOCIAL
            self._state.confidence = self.BASELINE_CONFIDENCE
            self._state.uncertainty = self.BASELINE_UNCERTAINTY
            self._state.curiosity = self.BASELINE_CURIOSITY
            self._state.frustration = self.BASELINE_FRUSTRATION

    def _clamp_locked(self) -> None:
        s = self._state
        s.arousal = min(1.0, max(0.0, float(s.arousal)))
        s.urgency = min(1.0, max(0.0, float(s.urgency)))
        s.social_engagement = min(1.0, max(0.0, float(s.social_engagement)))
        s.confidence = min(self.CONFIDENCE_MAX, max(self.CONFIDENCE_MIN, float(s.confidence)))
        s.uncertainty = min(self.UNCERTAINTY_MAX, max(self.UNCERTAINTY_MIN, float(s.uncertainty)))
        s.curiosity = min(1.0, max(0.0, float(s.curiosity)))
        s.frustration = min(1.0, max(0.0, float(s.frustration)))

    def step_decay(self, dt: float = 0.1) -> None:
        """Decays elevated/depressed modulators towards baseline equilibria.
        
        Args:
            dt: Elapsed time in seconds since last step (default 0.1s for 10 Hz loop).
        """
        with self._lock:
            ratio = max(0.0, dt / 0.1)
            s = self._state

            # Helper for linear proportional decay with snap-to-baseline
            def _decay(current: float, baseline: float, rate: float) -> float:
                diff = baseline - current
                step_change = diff * min(1.0, rate * ratio)
                if abs(diff) < 0.001:
                    return baseline
                return current + step_change

            s.arousal = _decay(s.arousal, self.BASELINE_AROUSAL, self.DECAY_RATE_AROUSAL)
            s.urgency = _decay(s.urgency, self.BASELINE_URGENCY, self.DECAY_RATE_URGENCY)
            s.social_engagement = _decay(s.social_engagement, self.BASELINE_SOCIAL, self.DECAY_RATE_SOCIAL)
            s.curiosity = _decay(s.curiosity, self.BASELINE_CURIOSITY, self.DECAY_RATE_CURIOSITY)
            s.frustration = _decay(s.frustration, self.BASELINE_FRUSTRATION, self.DECAY_RATE_FRUSTRATION)
            s.confidence = _decay(s.confidence, self.BASELINE_CONFIDENCE, self.DECAY_RATE_CONFIDENCE)
            s.uncertainty = _decay(s.uncertainty, self.BASELINE_UNCERTAINTY, self.DECAY_RATE_UNCERTAINTY)

            self._clamp_locked()

    # -------------------------------------------------------------------------
    # Modulator Adjustments
    # -------------------------------------------------------------------------

    def modulate_arousal(self, delta: float) -> None:
        with self._lock:
            self._state.arousal += delta
            self._clamp_locked()

    def modulate_urgency(self, delta: float) -> None:
        with self._lock:
            self._state.urgency += delta
            self._clamp_locked()

    def modulate_social_engagement(self, delta: float) -> None:
        with self._lock:
            self._state.social_engagement += delta
            self._clamp_locked()

    def modulate_curiosity(self, delta: float) -> None:
        with self._lock:
            self._state.curiosity += delta
            self._clamp_locked()

    def modulate_frustration(self, delta: float) -> None:
        with self._lock:
            self._state.frustration += delta
            self._clamp_locked()

    def set_confidence(self, val: float) -> None:
        with self._lock:
            self._state.confidence = float(val)
            self._clamp_locked()

    def update_confidence(self, delta: float) -> None:
        with self._lock:
            self._state.confidence += delta
            self._clamp_locked()

    def set_uncertainty(self, val: float) -> None:
        with self._lock:
            self._state.uncertainty = float(val)
            self._clamp_locked()

    def update_uncertainty(self, delta: float) -> None:
        with self._lock:
            self._state.uncertainty += delta
            self._clamp_locked()

    def record_failure(self, severity: float = 0.2) -> None:
        """Records an action or prediction failure, increasing frustration and uncertainty."""
        with self._lock:
            sev = max(0.05, min(0.5, severity))
            self._state.frustration += sev
            self._state.confidence -= (sev * 0.5)
            self._state.uncertainty += (sev * 0.5)
            self._clamp_locked()

    def record_success(self, magnitude: float = 0.15) -> None:
        """Records an action success or confirmed prediction, restoring confidence."""
        with self._lock:
            mag = max(0.05, min(0.4, magnitude))
            self._state.frustration = max(0.0, self._state.frustration - mag)
            self._state.confidence += mag
            self._state.uncertainty = max(0.0, self._state.uncertainty - mag)
            self._clamp_locked()

    # -------------------------------------------------------------------------
    # Event & Perception Ingestion
    # -------------------------------------------------------------------------

    def update_from_event(self, event: CognitiveEvent) -> None:
        """Modulates behavioral state based on canonical cognitive events."""
        with self._lock:
            t = event.event_type

            if t == CognitiveEventType.PERSON_APPEARED:
                self._state.arousal += 0.2
                self._state.social_engagement += 0.3

            elif t == CognitiveEventType.PERSON_RETURNED:
                self._state.social_engagement += 0.35
                self._state.confidence += 0.05

            elif t == CognitiveEventType.PERSON_DISAPPEARED:
                self._state.social_engagement = max(0.0, self._state.social_engagement - 0.2)

            elif t == CognitiveEventType.PERSON_SPOKE:
                self._state.social_engagement += 0.2
                self._state.arousal += 0.1

            elif t == CognitiveEventType.ROBOT_INTERRUPTED:
                self._state.arousal += 0.3
                self._state.frustration += 0.1
                self._state.urgency += 0.1

            elif t in (
                CognitiveEventType.ACTION_FAILED,
                CognitiveEventType.PREDICTION_ERROR,
                CognitiveEventType.GOAL_FAILED,
            ):
                self.record_failure(severity=0.2)

            elif t in (
                CognitiveEventType.ACTION_SUCCEEDED,
                CognitiveEventType.PREDICTION_CONFIRMED,
                CognitiveEventType.GOAL_COMPLETED,
            ):
                self.record_success(magnitude=0.15)

            elif t == CognitiveEventType.NOVELTY_DETECTED:
                self._state.curiosity += 0.3
                self._state.arousal += 0.2

            elif t in (
                CognitiveEventType.SENSOR_LOST,
                CognitiveEventType.CAPABILITY_DEGRADED,
            ):
                self._state.urgency += 0.35
                self._state.uncertainty += 0.2
                self._state.confidence -= 0.15

            elif t == CognitiveEventType.SENSOR_RECOVERED:
                self._state.uncertainty = max(0.0, self._state.uncertainty - 0.15)
                self._state.confidence += 0.1

            self._clamp_locked()

    def update_from_perception(self, perception: Dict[str, Any]) -> None:
        """Modulates state from immediate perception features."""
        with self._lock:
            # Urgent obstacle clearance
            env = perception.get("environment", {})
            front_m = env.get("front_clearance_m")
            if front_m is None:
                front_m = perception.get("min_front_distance_m")

            if front_m is not None and float(front_m) < 0.5:
                # Critical proximity trigger
                self._state.urgency = max(self._state.urgency, 0.7)
                self._state.arousal = max(self._state.arousal, 0.6)

            # Social signals
            if perception.get("vad", False):
                self._state.social_engagement = min(1.0, self._state.social_engagement + 0.1)
            if perception.get("looking_at_robot", False):
                self._state.social_engagement = min(1.0, self._state.social_engagement + 0.1)

            self._clamp_locked()

    # -------------------------------------------------------------------------
    # Behavioral Modulation Factors (Read-Only Queries)
    # -------------------------------------------------------------------------

    def get_reaction_speed_multiplier(self) -> float:
        """Computes reaction speed factor (1.0 = normal, >1.0 = faster)."""
        with self._lock:
            return 1.0 + (self._state.arousal * 0.4) + (self._state.urgency * 0.6)

    def get_verbosity_multiplier(self) -> float:
        """Computes dialogue verbosity factor (higher = more verbose, lower = concise)."""
        with self._lock:
            base = 1.0 + (self._state.social_engagement * 0.3) + (self._state.confidence * 0.2)
            penalty = (self._state.urgency * 0.5) + (self._state.frustration * 0.3)
            return max(0.2, base - penalty)

    def get_attention_sensitivity(self) -> float:
        """Computes attention salience threshold sensitivity (higher = more reactive)."""
        with self._lock:
            return 1.0 + (self._state.arousal * 0.5) + (self._state.curiosity * 0.3)
