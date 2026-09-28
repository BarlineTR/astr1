"""ASTRO V1 — Action Expectation Factory & General Prediction Generation.

Maps physical ActionIntents into rigorous, measurable outcome expectations
for deterministic closed-loop evaluation by PredictionEngine.

ARCHITECTURAL INVARIANTS:
1. STRICTLY MEASURABLE: No boolean 'True' placeholders. Values are numerical coordinates,
   velocities, angles, or standardized status tokens.
2. ZERO LLM: Pure deterministic mapping from ActionIntent semantics.
3. PREDICTION ID CONTRACT: Matches standard ASTRO Prediction contract.
"""

from __future__ import annotations

import time
from typing import Any, Dict, Optional

from astro_ai.contracts.consciousness_types import (
    ActionIntent,
    Prediction,
    PredictionStatus,
    SelfState,
)


class ActionExpectationFactory:
    """Factory generating structured, measurable Action Expectations for ActionIntents."""

    @staticmethod
    def create_expectation(
        action_intent: ActionIntent,
        current_state: Optional[SelfState] = None,
        now: Optional[float] = None,
    ) -> Optional[Prediction]:
        """Creates an action outcome prediction from an ActionIntent.

        Returns None if the action is passive or produces no measurable physical expectation.
        """
        if action_intent is None:
            return None

        ts = time.time() if now is None else now
        atype = action_intent.action_type
        params = action_intent.parameters or {}

        if atype == "turn_head":
            target_yaw = float(params.get("target_yaw_deg", 0.0))
            pred_id = f"pred_head_{action_intent.intent_id}"
            return Prediction(
                prediction_id=pred_id,
                action_id="turn_head",
                expected_state={"head_yaw_deg": round(target_yaw, 1)},
                expected_by=ts + 2.5,
                confidence_weight=1.0,
                target_person_id=action_intent.target,
                source="turn_head_action",
                created_at=ts,
                status=PredictionStatus.PENDING,
            )

        elif atype == "move_robot":
            direction = str(params.get("direction", "")).lower()
            linear_x = float(params.get("linear_x", 0.0))
            if not direction:
                if linear_x > 0.01:
                    direction = "forward"
                elif linear_x < -0.01:
                    direction = "backward"
                else:
                    direction = "stop"

            if direction == "stop":
                pred_id = f"pred_stop_{action_intent.intent_id}"
                return Prediction(
                    prediction_id=pred_id,
                    action_id="stop_robot",
                    expected_state={"velocity": 0.0, "is_stopped": 1.0},
                    expected_by=ts + 1.5,
                    confidence_weight=1.0,
                    source="move_robot_stop",
                    created_at=ts,
                    status=PredictionStatus.PENDING,
                )
            elif direction == "forward":
                speed = float(params.get("speed", linear_x or 0.20))
                duration = float(params.get("duration", 1.0))
                dist = float(params.get("distance_m", round(speed * duration, 2)))
                pred_id = f"pred_move_{action_intent.intent_id}"
                return Prediction(
                    prediction_id=pred_id,
                    action_id="move_forward",
                    expected_state={"velocity": speed, "distance_traveled_m": dist},
                    expected_by=ts + duration + 1.5,
                    confidence_weight=1.0,
                    source="move_robot_forward",
                    created_at=ts,
                    status=PredictionStatus.PENDING,
                )
            elif direction in ("left", "right"):
                pred_id = f"pred_align_{action_intent.intent_id}"
                return Prediction(
                    prediction_id=pred_id,
                    action_id="align_body",
                    expected_state={"relative_target_bearing_deg": 0.0},
                    expected_by=ts + 2.0,
                    confidence_weight=0.8,
                    source="align_body",
                    created_at=ts,
                    status=PredictionStatus.PENDING,
                )
            elif direction == "backward":
                speed = float(params.get("speed", 0.15))
                duration = float(params.get("duration", 0.8))
                dist = round(-speed * duration, 2)
                pred_id = f"pred_retreat_{action_intent.intent_id}"
                return Prediction(
                    prediction_id=pred_id,
                    action_id="move_backward",
                    expected_state={"velocity": -speed, "distance_traveled_m": dist},
                    expected_by=ts + duration + 1.5,
                    confidence_weight=0.8,
                    source="move_backward",
                    created_at=ts,
                    status=PredictionStatus.PENDING,
                )

        elif atype == "track_gaze":
            pred_id = f"pred_gaze_{action_intent.intent_id}"
            return Prediction(
                prediction_id=pred_id,
                action_id="track_gaze",
                expected_state={"gaze_error_deg": 0.0},
                expected_by=ts + 2.0,
                confidence_weight=0.8,
                target_person_id=action_intent.target,
                source="track_gaze",
                created_at=ts,
                status=PredictionStatus.PENDING,
            )

        elif atype in ("gesture", "gaze_aversion"):
            # Internal expressive motor behaviors do not yield external environmental predictions
            return None

        return None

    create_expectation_for_action = create_expectation
