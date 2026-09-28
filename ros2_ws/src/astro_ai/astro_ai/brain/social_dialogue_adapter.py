"""ASTRO V1 — Social Dialogue Adapter (Phase 5).

Converts authoritative internal CognitiveContext and SelfModel state into
compact, token-minimized DialogueContext envelopes. Enforces context delta
fingerprinting (SHA-256) to ensure zero re-transmissions when context is unchanged.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional, Tuple

from astro_ai.contracts.consciousness_types import (
    CognitiveContext,
    CognitiveDecision,
    InformationSufficiency,
    MetacognitiveState,
)
from astro_ai.contracts.person_state import UnifiedPersonState
from astro_ai.contracts.social_dialogue_types import (
    ConfidenceBracket,
    DialogueContext,
    DialogueContextUpdate,
    DialogueDirective,
    EpistemicDirective,
)

_LOG = logging.getLogger(__name__)


class DialogueContextAdapter:
    """Adapts cognitive and self-model state into minimal dialogue envelopes with delta tracking."""

    def __init__(self):
        self._last_fingerprint: Optional[str] = None
        self._last_context: Optional[DialogueContext] = None
        self.total_evaluations: int = 0
        self.total_updates_emitted: int = 0
        self.suppressed_updates: int = 0

    def adapt(
        self,
        self_model: Optional[Any] = None,
        cognitive_context: Optional[CognitiveContext] = None,
        person_state: Optional[UnifiedPersonState] = None,
        person_name: Optional[str] = None,
        formal_title: Optional[str] = None,
        is_verified: Optional[bool] = None,
        distance_m: Optional[float] = None,
        social_phase: Optional[str] = None,
        cognitive_decision: Optional[CognitiveDecision] = None,
        perception_data: Optional[Dict[str, Any]] = None,
    ) -> DialogueContext:
        """Derives a minimal DialogueContext from cognitive sources.

        Guarantees no internal UUIDs, database blobs, or raw sensor arrays are included.
        """
        # 1. Resolve Interlocutor & Verification
        name_val = "Misafir"
        title_val = "Misafir"
        verified_val = False
        focused_person = None
        dist_val = distance_m

        if person_state is not None:
            name_val = person_state.name or "Misafir"
            title_val = person_state.formal_title or name_val
            verified_val = bool(person_state.is_known and person_state.identity_confidence >= 0.70)
            focused_person = person_state.person_id
            if dist_val is None:
                dist_val = person_state.distance_m

        if person_name is not None:
            name_val = person_name
        if formal_title is not None:
            title_val = formal_title
        if is_verified is not None:
            verified_val = is_verified

        # 2. Activity & Operational State
        activity_val = "Etkileşimde"
        if self_model is not None:
            activity_val = self_model.get_current_activity()
            if focused_person is None:
                focused_person = self_model.get_focused_person()
        elif cognitive_context is not None:
            activity_val = cognitive_context.activity
            if focused_person is None:
                focused_person = cognitive_context.focused_person_id

        # 3. Active Goal (Description only — NO UUID)
        goal_desc = None
        if self_model is not None:
            g = self_model.get_active_goal()
            if g is not None:
                goal_desc = str(g.description).strip()
        elif cognitive_context is not None and cognitive_context.active_goal:
            goal_desc = str(cognitive_context.active_goal.get("description", "")).strip() or None

        # 4. Confidence Bracket & Epistemic Metrics
        conf_num = 0.60
        urgency_val = 0.0
        if self_model is not None:
            conf_num = self_model.get_confidence()
            aff = getattr(self_model, "affective_manager", None)
            if aff and hasattr(aff, "state"):
                urgency_val = float(getattr(aff.state, "urgency", 0.0))
        elif cognitive_context is not None:
            conf_num = cognitive_context.confidence
            aff_dict = cognitive_context.affective_state or {}
            urgency_val = float(aff_dict.get("urgency", 0.0))

        bracket = ConfidenceBracket.from_continuous(conf_num)

        # 5. Information Sufficiency & Epistemic Boundaries
        suff_str = "SUFFICIENT"
        if self_model is not None:
            try:
                suff_enum = self_model.assess_information_sufficiency(perception_data=perception_data)
                suff_str = suff_enum.value if hasattr(suff_enum, "value") else str(suff_enum)
            except Exception:
                suff_str = "SUFFICIENT"
        elif cognitive_context is not None and cognitive_context.metacognitive_state:
            suff_str = str(
                cognitive_context.metacognitive_state.get("information_sufficiency", "SUFFICIENT")
            )

        # 6. Active Conflicts
        conflicts_list: List[str] = []
        if self_model is not None:
            try:
                active_confs = self_model.metacognitive_engine.current_conflicts
                conflicts_list = [c.conflict_type for c in active_confs]
            except Exception:
                conflicts_list = []
        elif cognitive_context is not None and cognitive_context.metacognitive_state:
            c_state = cognitive_context.metacognitive_state.get("cognitive_conflict_state", "NONE")
            if c_state and c_state != "NONE":
                conflicts_list = [c_state]

        # 7. Cognitive Decision
        dec_type_str: Optional[str] = None
        if cognitive_decision is not None:
            dec_type_str = (
                cognitive_decision.decision_type.value
                if hasattr(cognitive_decision.decision_type, "value")
                else str(cognitive_decision.decision_type)
            )

        # 8. Distance from perception if still not set
        if dist_val is None and perception_data:
            if "spatial_user" in perception_data:
                dist_val = perception_data["spatial_user"].get("distance_m")
            elif "front_distance_m" in perception_data:
                dist_val = perception_data["front_distance_m"]

        ctx = DialogueContext(
            interlocutor_name=name_val,
            formal_title=title_val,
            is_verified=verified_val,
            focused_person_id=focused_person,
            current_activity=activity_val,
            active_goal_description=goal_desc,
            confidence_bracket=bracket,
            information_sufficiency=suff_str,
            epistemic_limitation="Görsel ya da hafıza bilgisi yoksa uydurma yapma; 'bilmiyorum' veya 'göremiyorum' de.",
            distance_m=round(dist_val, 2) if dist_val is not None else None,
            urgency_level=round(urgency_val, 2),
            social_phase=str(social_phase or "ENGAGED"),
            active_conflicts=conflicts_list,
            cognitive_decision_type=dec_type_str,
            timestamp=time.time(),
        )
        return ctx

    def check_delta(
        self,
        new_context: DialogueContext,
        directive: Optional[DialogueDirective] = None,
    ) -> DialogueContextUpdate:
        """Evaluates whether the dialogue context has changed.

        If unchanged (same fingerprint), returns has_changed=False and skips prompt generation.
        If changed, returns has_changed=True with the new fingerprint and formatted prompt.
        """
        self.total_evaluations += 1
        new_fp = new_context.compute_fingerprint()
        prev_fp = self._last_fingerprint

        if prev_fp is not None and new_fp == prev_fp:
            self.suppressed_updates += 1
            return DialogueContextUpdate(
                has_changed=False,
                fingerprint=new_fp,
                previous_fingerprint=prev_fp,
                changed_fields=[],
                formatted_prompt="",
                timestamp=time.time(),
            )

        # Determine which fields changed
        changed_fields: List[str] = []
        if self._last_context is not None:
            old = self._last_context
            if old.interlocutor_name != new_context.interlocutor_name:
                changed_fields.append("interlocutor_name")
            if old.formal_title != new_context.formal_title:
                changed_fields.append("formal_title")
            if old.is_verified != new_context.is_verified:
                changed_fields.append("is_verified")
            if old.focused_person_id != new_context.focused_person_id:
                changed_fields.append("focused_person_id")
            if old.current_activity != new_context.current_activity:
                changed_fields.append("current_activity")
            if old.active_goal_description != new_context.active_goal_description:
                changed_fields.append("active_goal_description")
            if old.confidence_bracket != new_context.confidence_bracket:
                changed_fields.append("confidence_bracket")
            if old.information_sufficiency != new_context.information_sufficiency:
                changed_fields.append("information_sufficiency")
            if (old.distance_m is None) != (new_context.distance_m is None) or (
                old.distance_m is not None
                and new_context.distance_m is not None
                and abs(old.distance_m - new_context.distance_m) >= 0.3
            ):
                changed_fields.append("distance_m")
            if abs(old.urgency_level - new_context.urgency_level) >= 0.2:
                changed_fields.append("urgency_level")
            if old.social_phase != new_context.social_phase:
                changed_fields.append("social_phase")
            if set(old.active_conflicts) != set(new_context.active_conflicts):
                changed_fields.append("active_conflicts")
            if old.cognitive_decision_type != new_context.cognitive_decision_type:
                changed_fields.append("cognitive_decision_type")
        else:
            changed_fields.append("initial_context")

        self._last_fingerprint = new_fp
        self._last_context = new_context
        self.total_updates_emitted += 1

        formatted = new_context.format_compact_prompt(directive=directive)
        return DialogueContextUpdate(
            has_changed=True,
            fingerprint=new_fp,
            previous_fingerprint=prev_fp,
            changed_fields=changed_fields,
            formatted_prompt=formatted,
            timestamp=time.time(),
        )

    def reset(self) -> None:
        """Resets delta state and counters for deterministic testing."""
        self._last_fingerprint = None
        self._last_context = None
        self.total_evaluations = 0
        self.total_updates_emitted = 0
        self.suppressed_updates = 0
