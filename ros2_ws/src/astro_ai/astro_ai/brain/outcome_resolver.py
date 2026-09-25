"""ASTRO V1 — Outcome Resolver.

Resolves empirical sensor and world observations into structured ActualOutcome instances
to evaluate pending predictions without cluttering CognitiveLoop.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from astro_ai.brain.world_model import WorldModel
from astro_ai.contracts.consciousness_types import (
    ActualOutcome,
    Prediction,
    SelfState,
)


class OutcomeResolver:
    """Evaluates sensory state against active predictions to generate ActualOutcomes."""

    @staticmethod
    def resolve_outcomes(
        active_predictions: List[Prediction],
        self_state: SelfState,
        world_model: WorldModel,
        perception_data: Optional[Dict[str, Any]] = None,
        now: Optional[float] = None,
    ) -> List[ActualOutcome]:
        """Inspects current physical state & world model to produce matching ActualOutcomes."""
        ts = time.time() if now is None else now
        outcomes: List[ActualOutcome] = []

        for p in active_predictions:
            # 1. Perceptual: Face arrival after head attention
            if p.action_id == "EXPECT_FACE_AFTER_HEAD_ATTENTION":
                visual_people = [
                    per for per in world_model._people.values()
                    if getattr(per, "is_present", False) and getattr(per, "has_vision", False)
                ]
                if visual_people:
                    if "face_detected" in p.expected_state:
                        act_state = {"face_detected": True}
                    else:
                        act_state = {"face_status": "DETECTED"}
                    outcomes.append(
                        ActualOutcome(
                            outcome_id=f"out_face_{int(ts * 1000)}",
                            expectation_id=p.prediction_id,
                            actual_state=act_state,
                            timestamp=ts,
                            source="camera_vision",
                        )
                    )

            # 2. Motor: Head turn angle reached
            elif p.action_id == "turn_head" and "head_yaw_deg" in p.expected_state:
                exp_yaw = float(p.expected_state["head_yaw_deg"])
                actual_yaw = float(self_state.current_head_yaw_deg)
                if abs(actual_yaw - exp_yaw) <= 5.0:
                    outcomes.append(
                        ActualOutcome(
                            outcome_id=f"out_yaw_{int(ts * 1000)}",
                            expectation_id=p.prediction_id,
                            actual_state={"head_yaw_deg": round(actual_yaw, 1)},
                            timestamp=ts,
                            source="head_servo_feedback",
                        )
                    )

            # 3. Motor: Stop robot
            elif p.action_id == "stop_robot" and "velocity" in p.expected_state:
                outcomes.append(
                    ActualOutcome(
                        outcome_id=f"out_stop_{int(ts * 1000)}",
                        expectation_id=p.prediction_id,
                        actual_state={"velocity": 0.0},
                        timestamp=ts,
                        source="base_stop_confirmed",
                    )
                )

            # 4. Motor: Align body
            elif p.action_id == "align_body" and "relative_target_bearing_deg" in p.expected_state:
                target_id = p.target_person_id
                target_p = world_model._people.get(target_id) if target_id else None
                if target_p and abs(float(target_p.azimuth_deg)) <= 5.0:
                    outcomes.append(
                        ActualOutcome(
                            outcome_id=f"out_align_{int(ts * 1000)}",
                            expectation_id=p.prediction_id,
                            actual_state={"relative_target_bearing_deg": round(target_p.azimuth_deg, 1)},
                            timestamp=ts,
                            source="body_alignment_feedback",
                        )
                    )

            # 5. Gaze: Target tracking convergence
            elif p.action_id == "track_gaze" and "gaze_error_deg" in p.expected_state:
                target_id = p.target_person_id
                target_p = world_model._people.get(target_id) if target_id else None
                if target_p and (getattr(target_p, "has_vision", False) or getattr(target_p, "is_present", False)):
                    gaze_err = abs(float(getattr(target_p, "azimuth_deg", 0.0) or 0.0))
                    # Converged within visual tolerance (15° FOV) or visually grounded
                    if gaze_err <= 15.0 or (perception_data and perception_data.get("person_detected")):
                        outcomes.append(
                            ActualOutcome(
                                outcome_id=f"out_gaze_{int(ts * 1000)}",
                                expectation_id=p.prediction_id,
                                actual_state={"gaze_error_deg": 0.0},
                                timestamp=ts,
                                source="gaze_tracker_convergence",
                            )
                        )
                elif perception_data and perception_data.get("person_detected"):
                    outcomes.append(
                        ActualOutcome(
                            outcome_id=f"out_gaze_{int(ts * 1000)}",
                            expectation_id=p.prediction_id,
                            actual_state={"gaze_error_deg": 0.0},
                            timestamp=ts,
                            source="gaze_tracker_visual_presence",
                        )
                    )

            # 6. Gesture & gaze aversion internal execution confirmation
            elif p.action_id.startswith("gesture_") or p.action_id in ("gesture", "gaze_aversion"):
                outcomes.append(
                    ActualOutcome(
                        outcome_id=f"out_gest_{int(ts * 1000)}",
                        expectation_id=p.prediction_id,
                        actual_state=dict(p.expected_state),
                        timestamp=ts,
                        source="internal_motor_gesture_feedback",
                    )
                )

        return outcomes
