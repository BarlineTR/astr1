"""ASTRO V1 — Prediction Engine & Deterministic Outcome Evaluation.

Governs:
  - Action expectations and prediction lifecycle (PENDING -> CONFIRMED / MISMATCH / EXPIRED)
  - Deterministic mismatch calculation against actual outcomes
  - Bounded mathematical updates for confidence and uncertainty
  - Detection of expired expectations

ARCHITECTURAL INVARIANTS:
  1. STRICTLY DETERMINISTIC: All evaluations produce identical outputs for identical inputs.
  2. BOUNDED OUTPUTS: Confidence clamped to [0.1, 1.0], uncertainty clamped to [0.0, 1.0].
  3. NO LLM IN LOOP: Prediction evaluation is pure algorithmic math, zero network calls.
"""

from __future__ import annotations

import logging
import math
import threading
import time
from typing import Any, Dict, List, Optional

from astro_ai.contracts.consciousness_types import (
    ActualOutcome,
    Prediction,
    PredictionError,
    PredictionStatus,
)

_LOG = logging.getLogger(__name__)

# Canonical configurable constants for prediction-outcome dynamics
PREDICTION_MATCH_CONFIDENCE_DELTA: float = 0.05
PREDICTION_MATCH_UNCERTAINTY_DELTA: float = -0.05
PREDICTION_MISMATCH_PENALTY_FACTOR: float = 0.2

CONFIDENCE_MIN: float = 0.1
CONFIDENCE_MAX: float = 1.0
UNCERTAINTY_MIN: float = 0.0
UNCERTAINTY_MAX: float = 1.0


class PredictionEngine:
    """Thread-safe engine managing predictions and deterministic outcome evaluation."""

    def __init__(
        self,
        match_confidence_delta: float = PREDICTION_MATCH_CONFIDENCE_DELTA,
        match_uncertainty_delta: float = PREDICTION_MATCH_UNCERTAINTY_DELTA,
        mismatch_penalty_factor: float = PREDICTION_MISMATCH_PENALTY_FACTOR,
    ):
        self._lock = threading.RLock()
        self._predictions: Dict[str, Prediction] = {}
        self.match_confidence_delta = float(match_confidence_delta)
        self.match_uncertainty_delta = float(match_uncertainty_delta)
        self.mismatch_penalty_factor = float(mismatch_penalty_factor)

    def register_prediction(self, prediction: Prediction) -> None:
        """Registers a new action expectation to be verified against future outcomes."""
        with self._lock:
            self._predictions[prediction.prediction_id] = prediction

    def get_prediction(self, prediction_id: str) -> Optional[Prediction]:
        """Retrieves a prediction by ID."""
        with self._lock:
            return self._predictions.get(prediction_id)

    def get_active_predictions(self) -> List[Prediction]:
        """Returns all predictions currently pending evaluation."""
        with self._lock:
            return [
                p for p in self._predictions.values()
                if p.status == PredictionStatus.PENDING
            ]

    @property
    def active_predictions(self) -> List[Prediction]:
        """Convenience property returning all active pending predictions."""
        return self.get_active_predictions()

    def remove_prediction(self, prediction_id: str) -> Optional[Prediction]:
        """Removes a prediction from tracking."""
        with self._lock:
            return self._predictions.pop(prediction_id, None)

    def clear(self) -> None:
        """Clears all stored predictions."""
        with self._lock:
            self._predictions.clear()

    def create_perceptual_prediction(
        self,
        prediction_type: str,
        target_id: str,
        expected_state: Dict[str, Any],
        timeout_seconds: float = 2.0,
        confidence_weight: float = 1.0,
        now: Optional[float] = None,
    ) -> Prediction:
        """Helper to create and register a structured perceptual prediction for World Model.

        Canonical Phase 6 prediction types:
          - EXPECT_PERSON_APPROACHING
          - EXPECT_PERSON_REAPPEAR
          - EXPECT_FACE_AFTER_HEAD_ATTENTION
          - EXPECT_AUDIO_SOURCE_CONTINUES
        """
        with self._lock:
            ts = time.time() if now is None else now
            pred_id = f"pred_{prediction_type.lower()}_{target_id}_{int(ts * 1000) % 100000}"
            pred = Prediction(
                prediction_id=pred_id,
                action_id=prediction_type,
                expected_state=expected_state,
                expected_by=ts + max(0.2, timeout_seconds),
                confidence_weight=confidence_weight,
                created_at=ts,
                target_person_id=target_id,
                status=PredictionStatus.PENDING,
            )
            self._predictions[pred_id] = pred
            return pred

    # -------------------------------------------------------------------------
    # Evaluation Logic
    # -------------------------------------------------------------------------

    def calculate_discrepancy(
        self, expected: Dict[str, Any], actual: Dict[str, Any]
    ) -> tuple[float, str, Dict[str, Any]]:
        """Calculates discrepancy score [0.0, 1.0], mismatch type, and mismatch details.

        Returns:
            (mismatch_score, mismatch_type, details)
        """
        if not expected:
            return 0.0, "NONE", {}

        mismatched_keys: List[str] = []
        missing_keys: List[str] = []
        details: Dict[str, Any] = {}

        total_keys = len(expected)
        for key, exp_val in expected.items():
            if key not in actual:
                missing_keys.append(key)
                details[key] = {"expected": exp_val, "actual": None, "reason": "MISSING"}
            else:
                act_val = actual[key]
                if isinstance(exp_val, (int, float)) and isinstance(act_val, (int, float)):
                    tol = 1e-3
                    if "yaw" in key or "deg" in key or "bearing" in key:
                        tol = 5.0
                    elif "vel" in key or "speed" in key:
                        tol = 0.05
                    elif "dist" in key or "clearance" in key:
                        tol = 0.2
                    if not math.isclose(float(exp_val), float(act_val), abs_tol=tol):
                        mismatched_keys.append(key)
                        details[key] = {"expected": exp_val, "actual": act_val, "reason": "VALUE_DIFF"}
                elif exp_val != act_val:
                    mismatched_keys.append(key)
                    details[key] = {"expected": exp_val, "actual": act_val, "reason": "VALUE_DIFF"}

        num_discrepancies = len(mismatched_keys) + len(missing_keys)
        mismatch_score = min(1.0, max(0.0, float(num_discrepancies) / float(total_keys)))

        if num_discrepancies == 0:
            mismatch_type = "NONE"
        elif missing_keys and not mismatched_keys:
            mismatch_type = "MISSING_KEYS"
        elif mismatched_keys and not missing_keys:
            mismatch_type = "VALUE_MISMATCH"
        else:
            mismatch_type = "STATE_MISMATCH"

        return mismatch_score, mismatch_type, details

    def evaluate_outcome(
        self, outcome: ActualOutcome, now: Optional[float] = None
    ) -> PredictionError:
        """Evaluates an observed outcome against a tracked prediction.

        Calculates deterministic mismatch score, updates prediction status,
        and computes signed confidence and uncertainty impacts.
        """
        with self._lock:
            ts = time.time() if now is None else now
            pred = self._predictions.get(outcome.expectation_id) if outcome.expectation_id else None

            if pred is None:
                # Outcome without matching prediction or unknown expectation ID
                return PredictionError(
                    expectation_id=outcome.expectation_id or "unmatched",
                    matched=False,
                    mismatch_score=1.0,
                    mismatch_type="UNMATCHED_OUTCOME",
                    confidence_impact=-0.05,
                    uncertainty_impact=0.05,
                    details={"outcome_id": outcome.outcome_id, "reason": "No matching prediction"},
                    timestamp=ts,
                )

            weight = max(0.1, min(2.0, float(pred.confidence_weight)))
            mismatch_score, mismatch_type, details = self.calculate_discrepancy(
                pred.expected_state, outcome.actual_state
            )

            if mismatch_score == 0.0:
                pred.status = PredictionStatus.CONFIRMED
                matched = True
                conf_impact = self.match_confidence_delta * weight
                unc_impact = self.match_uncertainty_delta * weight
            else:
                pred.status = PredictionStatus.MISMATCH
                matched = False
                penalty = mismatch_score * weight * self.mismatch_penalty_factor
                conf_impact = -penalty
                unc_impact = penalty

            pred_error = PredictionError(
                expectation_id=pred.prediction_id,
                matched=matched,
                mismatch_score=round(mismatch_score, 4),
                mismatch_type=mismatch_type,
                confidence_impact=round(conf_impact, 4),
                uncertainty_impact=round(unc_impact, 4),
                details=details,
                timestamp=ts,
            )
            return pred_error

    def check_expirations(self, now: Optional[float] = None) -> List[PredictionError]:
        """Checks all pending predictions for timeout expiry.

        Returns a list of PredictionError objects for any newly expired predictions.
        """
        with self._lock:
            ts = time.time() if now is None else now
            expired_errors: List[PredictionError] = []

            for pred in list(self._predictions.values()):
                if pred.status == PredictionStatus.PENDING and pred.is_expired(ts):
                    pred.status = PredictionStatus.EXPIRED
                    weight = max(0.1, min(2.0, float(pred.confidence_weight)))
                    penalty = 1.0 * weight * self.mismatch_penalty_factor
                    err = PredictionError(
                        expectation_id=pred.prediction_id,
                        matched=False,
                        mismatch_score=1.0,
                        mismatch_type="TIMEOUT_EXPIRED",
                        confidence_impact=round(-penalty, 4),
                        uncertainty_impact=round(penalty, 4),
                        details={
                            "action_id": pred.action_id,
                            "expected_by": pred.expected_by,
                            "expired_at": ts,
                        },
                        timestamp=ts,
                    )
                    expired_errors.append(err)

            return expired_errors
