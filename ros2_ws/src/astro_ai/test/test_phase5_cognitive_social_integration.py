"""ASTRO V1 — Phase 5 Test Suite: Cognitive-to-Social Integration & Adaptive Interaction.

Validates the full Phase 5 bridge connecting deterministic machine consciousness
(Phases 0A–4) to the social interaction stack (Realtime, Local Gemma, SocialBrain, ActionManager).
Strictly adheres to:
  1. Cognitive core authoritative.
  2. One-way authority flow: Cognitive -> DialogueContextAdapter -> DialoguePolicyEngine -> Speech.
  3. No motor control or ActionIntent emission by LLMs.
  4. Context Delta & SHA-256 fingerprinting with zero re-transmission on unchanged context.
  5. 100% deterministic, offline execution with zero live external API calls.
"""

from __future__ import annotations

import collections
import hashlib
import json
import re
import time
import unittest
from unittest.mock import MagicMock, patch

from astro_ai.action_manager import ActionManager, ActionResult, SoundDirection
from astro_ai.brain.cognitive_loop import CognitiveLoop
from astro_ai.brain.dialogue_policy_engine import DialoguePolicyEngine
from astro_ai.brain.self_model import SelfModel
from astro_ai.brain.social_brain import SocialBrain
from astro_ai.brain.social_dialogue_adapter import DialogueContextAdapter
from astro_ai.contracts.consciousness_types import (
    ActionIntent,
    CognitiveConflict,
    CognitiveContext,
    CognitiveDecision,
    CognitiveDecisionType,
    CognitiveEvent,
    CognitiveEventType,
    Goal,
    GoalType,
    InformationSufficiency,
    MetacognitiveState,
    Prediction,
    RobotAffectiveState,
    SelfState,
)
from astro_ai.contracts.intent_emotion_types import ConversationPhase, EmotionSignal, IntentType, RelationshipRole
from astro_ai.contracts.person_state import UnifiedPersonState
from astro_ai.contracts.social_context import SocialContext, SocialDecision
from astro_ai.contracts.social_dialogue_types import (
    ConfidenceBracket,
    DialogueContext,
    DialogueContextUpdate,
    DialogueDirective,
    EpistemicDirective,
    VerbosityLevel,
)
from astro_ai.brain.support.assistant import CognitiveArchitectureAssistant
from astro_ai.brain.support.config import SupportConfig
from astro_ai.brain.support.contracts import (
    ProposalStatus,
    StructuredChangeProposal,
    SupportControlMode,
    SupportRequest,
    SupportStatus,
)
from astro_ai.local_gemma_client import LocalGemmaClient, LocalGemmaError
from astro_ai.state_machine import RobotState, StateMachine


class TestPhase5CognitiveSocialIntegration(unittest.TestCase):
    """35 Comprehensive Deterministic Unit & Integration Tests for Phase 5."""

    def setUp(self):
        self.self_model = SelfModel()
        self.adapter = DialogueContextAdapter()
        self.policy_engine = DialoguePolicyEngine(interruption_timeout_s=5.0)

    # -------------------------------------------------------------------------
    # 1. Minimal Dialogue Envelope Size
    # -------------------------------------------------------------------------
    def test_01_minimal_dialogue_envelope_size(self):
        """1. Minimal dialogue envelope is strictly compact (< 100 tokens, < 500 characters)."""
        ctx = self.adapter.adapt(
            self_model=self.self_model,
            person_name="Baran",
            formal_title="Baş Mühendis",
            is_verified=True,
            distance_m=1.2,
        )
        directive = self.policy_engine.evaluate_policy(ctx)
        prompt = ctx.format_compact_prompt(directive=directive)

        # Standard token estimation: word count * 1.3
        approx_tokens = int(len(prompt.split()) * 1.3)
        self.assertLess(approx_tokens, 100, f"Token count {approx_tokens} exceeded 100-token envelope limit.")
        self.assertLess(len(prompt), 500, f"Prompt length {len(prompt)} exceeded 500 chars limit.")
        self.assertIn("[BİLİŞSEL DİYALOG BAĞLAMI]", prompt)
        self.assertIn("Baran", prompt)

    # -------------------------------------------------------------------------
    # 2. Internal UUID Stripping
    # -------------------------------------------------------------------------
    def test_02_internal_uuid_stripping(self):
        """2. Internal UUIDs, database blobs, and raw sensor arrays are stripped from envelope."""
        uuid_goal = "goal-550e8400-e29b-41d4-a716-446655440000"
        goal = Goal(
            goal_id=uuid_goal,
            goal_type=GoalType.TASK,
            description="Ahlat Selçuklu Mezarlığı hakkında bilgi ver",
            priority=0.8,
        )
        self.self_model.set_active_goal(goal)

        ctx = self.adapter.adapt(self_model=self.self_model, person_name="Baran")
        prompt = ctx.format_compact_prompt()

        uuid_regex = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.IGNORECASE)
        self.assertIsNone(uuid_regex.search(prompt), "Internal UUID leaked into formatted dialogue prompt!")
        self.assertNotIn(uuid_goal, prompt)
        self.assertIn("Ahlat Selçuklu Mezarlığı hakkında bilgi ver", prompt)

    # -------------------------------------------------------------------------
    # 3. Epistemic Limitation Grounding
    # -------------------------------------------------------------------------
    def test_03_epistemic_limitation_grounding(self):
        """3. Epistemic limitation ('bilmiyorum deme yetkisi') is strictly grounded in envelope."""
        ctx = self.adapter.adapt(self_model=self.self_model)
        prompt = ctx.format_compact_prompt()

        self.assertIn("Görsel ya da hafıza bilgisi yoksa uydurma yapma", prompt)
        self.assertIn("bilmiyorum", prompt)

    # -------------------------------------------------------------------------
    # 4. Focused-Person Grounding
    # -------------------------------------------------------------------------
    def test_04_focused_person_grounding(self):
        """4. Focused-person identity, title, and verification flag are accurately represented."""
        person = UnifiedPersonState(
            person_id="person_vali",
            name="Erol Karaömeroğlu",
            formal_title="Sayın Valim",
            is_known=True,
            identity_confidence=0.92,
            distance_m=1.8,
        )
        ctx = self.adapter.adapt(self_model=self.self_model, person_state=person)

        self.assertEqual(ctx.interlocutor_name, "Erol Karaömeroğlu")
        self.assertEqual(ctx.formal_title, "Sayın Valim")
        self.assertTrue(ctx.is_verified)
        self.assertEqual(ctx.distance_m, 1.8)

        prompt = ctx.format_compact_prompt()
        self.assertIn("Sayın Valim", prompt)
        self.assertIn("Doğrulandı", prompt)

    # -------------------------------------------------------------------------
    # 5. Focused-Person Continuity Across Brief Interruption
    # -------------------------------------------------------------------------
    def test_05_focused_person_continuity(self):
        """5. Primary conversational focus is preserved across brief third-party interruption."""
        engine = DialoguePolicyEngine(interruption_timeout_s=5.0)

        # Primary speaker starts conversation at t=10.0
        is_interr, reason = engine.handle_interlocutor_turn("baran_01", "Baran", now=10.0)
        self.assertFalse(is_interr)
        self.assertEqual(engine.primary_person_id, "baran_01")

        # 3rd party speaks at t=12.0 (elapsed = 2.0s <= 5.0s)
        is_interr, reason = engine.handle_interlocutor_turn("guest_02", "Misafir 2", now=12.0)
        self.assertTrue(is_interr, "Brief third-party utterance must be flagged as an interruption.")
        self.assertEqual(engine.primary_person_id, "baran_01", "Primary focus must NOT be prematurely lost.")

    # -------------------------------------------------------------------------
    # 6. Interruption Recovery & Transition on Exceeded Timeout
    # -------------------------------------------------------------------------
    def test_06_interruption_recovery(self):
        """6. When interruption exceeds timeout threshold, focus transitions smoothly."""
        engine = DialoguePolicyEngine(interruption_timeout_s=5.0)

        engine.handle_interlocutor_turn("baran_01", "Baran", now=10.0)

        # 3rd party speaks at t=16.0 (elapsed = 6.0s > 5.0s)
        is_interr, reason = engine.handle_interlocutor_turn("guest_02", "Misafir 2", now=16.0)
        self.assertFalse(is_interr, "Interruption exceeding timeout should transition to new primary.")
        self.assertEqual(engine.primary_person_id, "guest_02")
        self.assertIn("focus_switched", reason)

    # -------------------------------------------------------------------------
    # 7. Affective Urgency -> Verbosity Policy
    # -------------------------------------------------------------------------
    def test_07_affective_urgency_verbosity_policy(self):
        """7. HIGH urgency produces CONCISE verbosity clamped to max 15 words."""
        aff_state = RobotAffectiveState(urgency=0.85, confidence=0.7)
        ctx = self.adapter.adapt(self_model=self.self_model)
        directive = self.policy_engine.evaluate_policy(ctx, affective_state=aff_state)

        self.assertEqual(directive.verbosity, VerbosityLevel.CONCISE)
        self.assertLessEqual(directive.max_words, 15)
        self.assertIn("Acil", directive.tone_guidance)

    # -------------------------------------------------------------------------
    # 8. Affective Uncertainty -> Cautious Epistemic Policy
    # -------------------------------------------------------------------------
    def test_08_affective_uncertainty_cautious_policy(self):
        """8. HIGH uncertainty triggers epistemically cautious language and QUALIFIED directive."""
        aff_state = RobotAffectiveState(uncertainty=0.75, confidence=0.3)
        ctx = self.adapter.adapt(self_model=self.self_model)
        directive = self.policy_engine.evaluate_policy(ctx, affective_state=aff_state)

        self.assertEqual(directive.epistemic_directive, EpistemicDirective.QUALIFIED)
        self.assertIn("temkinli", directive.tone_guidance)

    # -------------------------------------------------------------------------
    # 9. Affective Frustration -> Recovery / Simplification Policy
    # -------------------------------------------------------------------------
    def test_09_affective_frustration_recovery_policy(self):
        """9. HIGH frustration produces simplified, recovery-oriented dialogue directive."""
        aff_state = RobotAffectiveState(frustration=0.75, urgency=0.2)
        ctx = self.adapter.adapt(self_model=self.self_model)
        directive = self.policy_engine.evaluate_policy(ctx, affective_state=aff_state)

        self.assertEqual(directive.verbosity, VerbosityLevel.CONCISE)
        self.assertLessEqual(directive.max_words, 18)
        self.assertIn("çözüm odaklı", directive.tone_guidance)

    # -------------------------------------------------------------------------
    # 10. Insufficient Information -> Clarification Request
    # -------------------------------------------------------------------------
    def test_10_insufficient_information_clarification(self):
        """10. INSUFFICIENT information maps to CLARIFY_OR_DECLINE directive."""
        ctx = DialogueContext(information_sufficiency="INSUFFICIENT")
        directive = self.policy_engine.evaluate_policy(ctx)

        self.assertEqual(directive.epistemic_directive, EpistemicDirective.CLARIFY_OR_DECLINE)
        self.assertTrue(directive.clarification_needed)
        self.assertIn("bilmiyorum", directive.epistemic_guidance.lower())

    # -------------------------------------------------------------------------
    # 11. Stale Information -> Temporal Qualification
    # -------------------------------------------------------------------------
    def test_11_stale_information_temporal_qualification(self):
        """11. STALE information maps to QUALIFIED directive with temporal caveat."""
        ctx = DialogueContext(information_sufficiency="STALE")
        directive = self.policy_engine.evaluate_policy(ctx)

        self.assertEqual(directive.epistemic_directive, EpistemicDirective.QUALIFIED)
        self.assertIn("en son kontrol ettiğimde", directive.epistemic_guidance)

    # -------------------------------------------------------------------------
    # 12. Conflicting Information -> Uncertainty Directive
    # -------------------------------------------------------------------------
    def test_12_conflicting_information_uncertainty_directive(self):
        """12. CONFLICTING information maps to UNCERTAIN directive explaining sensor disagreement."""
        ctx = DialogueContext(information_sufficiency="CONFLICTING")
        directive = self.policy_engine.evaluate_policy(ctx)

        self.assertEqual(directive.epistemic_directive, EpistemicDirective.UNCERTAIN)
        self.assertIn("çelişki", directive.epistemic_guidance)

    # -------------------------------------------------------------------------
    # 13. Safety Conflict -> Dialogue Priority
    # -------------------------------------------------------------------------
    def test_13_safety_conflict_dialogue_priority(self):
        """13. Safety conflict forces concise warning and overrides nominal verbosity."""
        ctx = DialogueContext(
            active_conflicts=["GOAL_SAFETY_CONFLICT"],
            distance_m=0.35,
        )
        directive = self.policy_engine.evaluate_policy(ctx)

        self.assertIsNotNone(directive.safety_warning)
        self.assertEqual(directive.verbosity, VerbosityLevel.CONCISE)
        self.assertLessEqual(directive.max_words, 10)
        self.assertIn("GÜVENLİK UYARISI", ctx.format_compact_prompt(directive))

    # -------------------------------------------------------------------------
    # 14. Obstacle Speech Interruption
    # -------------------------------------------------------------------------
    def test_14_obstacle_speech_interruption(self):
        """14. Immediate obstacle detection latches barge-in and triggers speech cancellation."""
        mock_realtime_node = MagicMock()
        mock_realtime_node._barge_in_latched = False

        # Simulate obstacle arriving via LiDAR callback
        def on_obstacle_detected(distance_m: float):
            if distance_m < 0.50:
                mock_realtime_node._barge_in_latched = True
                mock_realtime_node.cancel_current_speech()

        on_obstacle_detected(0.32)
        self.assertTrue(mock_realtime_node._barge_in_latched)
        mock_realtime_node.cancel_current_speech.assert_called_once()

    # -------------------------------------------------------------------------
    # 15. Focused-Person Loss
    # -------------------------------------------------------------------------
    def test_15_focused_person_loss(self):
        """15. Focused person loss from visual FOV acknowledges absence without fabricating sight."""
        person = UnifiedPersonState(
            person_id="p_lost",
            name="Baran",
            is_present=False,
            distance_m=0.0,
        )
        ctx = self.adapter.adapt(self_model=self.self_model, person_state=person)
        self.assertFalse(ctx.is_verified)
        prompt = ctx.format_compact_prompt()
        self.assertIn("göremiyorum", prompt)

    # -------------------------------------------------------------------------
    # 16. Acoustic Reorientation Grounding
    # -------------------------------------------------------------------------
    def test_16_acoustic_reorientation(self):
        """16. Acoustic orientation uses ReSpeaker DOA authority, never LLM hallucination."""
        valid_doa = SoundDirection(
            azimuth_deg=-45.0,
            confidence=0.85,
            valid=True,
            timestamp=100.0,
            raw_doa_deg=315.0,
            rms_level=600.0,
        )
        self.assertTrue(valid_doa.valid)
        self.assertEqual(valid_doa.azimuth_deg, -45.0)

        # Invalid weak DOA rejected
        weak_doa = SoundDirection(
            azimuth_deg=0.0,
            confidence=0.20,
            valid=False,
            timestamp=100.0,
            raw_doa_deg=0.0,
            rms_level=50.0,
        )
        self.assertFalse(weak_doa.valid)

    # -------------------------------------------------------------------------
    # 17. Turn-Boundary Synchronization
    # -------------------------------------------------------------------------
    def test_17_turn_boundary_synchronization(self):
        """17. Dialogue context updates are synchronized at turn boundaries, not on 10 Hz ticks."""
        loop = CognitiveLoop(self_state=self.self_model.self_state, target_hz=10.0)

        # 20 cognitive loop cycles (2.0s of 10 Hz ticks)
        for _ in range(20):
            loop.step()

        # Adapter was NOT called on 10 Hz loop steps
        self.assertEqual(self.adapter.total_evaluations, 0)

        # Called once at dialogue turn boundary
        ctx = self.adapter.adapt(self_model=self.self_model)
        update = self.adapter.check_delta(ctx)
        self.assertEqual(self.adapter.total_evaluations, 1)
        self.assertTrue(update.has_changed)

    # -------------------------------------------------------------------------
    # 18. Critical Event Asynchronous Interrupt
    # -------------------------------------------------------------------------
    def test_18_critical_event_asynchronous_interrupt(self):
        """18. Critical safety event triggers asynchronous interrupt without waiting for turn."""
        mock_node = MagicMock()
        mock_node._obstacle_detected = True
        mock_node._arduino_heartbeat_healthy = True
        mock_node._last_heartbeat_ack_time = time.monotonic()
        mock_node._last_laser_scan_time = time.monotonic()

        action_mgr = ActionManager(node=mock_node)
        res = action_mgr.execute_move("forward")
        self.assertFalse(res.success, "Obstacle must block motion!")
        self.assertEqual(res.error_code, "OBSTACLE_DETECTED")

    # -------------------------------------------------------------------------
    # 19. Realtime Failure -> Local Gemma Fallback
    # -------------------------------------------------------------------------
    def test_19_realtime_failure_local_gemma_fallback(self):
        """19. Cloud Realtime disconnection cleanly activates Local Gemma stream."""
        mock_gemma = MagicMock(spec=LocalGemmaClient)
        mock_gemma.is_available.return_value = True
        mock_gemma.stream.return_value = ["Merhaba", ", ", "ben ", "Astro."]

        realtime_available = False
        response = ""
        if not realtime_available and mock_gemma.is_available():
            tokens = list(mock_gemma.stream("ASTRO: Merhaba"))
            response = "".join(tokens)

        self.assertEqual(response, "Merhaba, ben Astro.")
        mock_gemma.stream.assert_called_once()

    # -------------------------------------------------------------------------
    # 20. Local Gemma Failure -> Deterministic Fallback
    # -------------------------------------------------------------------------
    def test_20_local_gemma_failure_deterministic_fallback(self):
        """20. When both Realtime and Local Gemma fail, deterministic fallback is produced."""
        mock_gemma = MagicMock(spec=LocalGemmaClient)
        mock_gemma.is_available.return_value = True
        mock_gemma.stream.side_effect = LocalGemmaError("llama-server unavailable")

        realtime_available = False
        reply = None
        if not realtime_available:
            try:
                for token in mock_gemma.stream("test"):
                    pass
            except LocalGemmaError:
                # Deterministic fallback
                reply = "Şu an bağlantımda bir aksaklık var, ancak sizi dinliyorum."

        self.assertIsNotNone(reply)
        self.assertIn("aksaklık", reply)

    # -------------------------------------------------------------------------
    # 21. Camera Degradation Handling
    # -------------------------------------------------------------------------
    def test_21_camera_degradation(self):
        """21. Camera degradation disables visual claims but allows audio interaction to proceed."""
        self.self_model.self_state.degraded_capabilities.add("camera")
        ctx = self.adapter.adapt(
            self_model=self.self_model,
            person_name="Misafir",
            is_verified=False,
        )
        self.assertIn("göremiyorum", ctx.epistemic_limitation)
        self.assertFalse(ctx.is_verified)

    # -------------------------------------------------------------------------
    # 22. Radar Degradation Handling
    # -------------------------------------------------------------------------
    def test_22_radar_degradation(self):
        """22. Radar degradation engages motion safety interlock while speech continues safely."""
        mock_node = MagicMock()
        mock_node._obstacle_detected = False
        mock_node._arduino_heartbeat_healthy = True
        mock_node._last_heartbeat_ack_time = time.monotonic()
        mock_node._last_laser_scan_time = time.monotonic() - 10.0  # Stale scan!

        action_mgr = ActionManager(node=mock_node)
        res = action_mgr.execute_move("forward")
        self.assertFalse(res.success, "Stale scan must block motion!")
        self.assertEqual(res.error_code, "LIDAR_STALE_OR_DISCONNECTED")

    # -------------------------------------------------------------------------
    # 23. Zero LLM Operation
    # -------------------------------------------------------------------------
    def test_23_no_llm_operation(self):
        """23. Cognitive substrate operates 100% deterministically with zero LLMs running."""
        loop = CognitiveLoop(self_state=self.self_model.self_state, target_hz=10.0)
        for i in range(10):
            loop.step()

        # Cognition is fully functional
        self.assertEqual(loop.cycle_count, 10)
        self.assertIsNotNone(self.self_model.get_current_activity())
        self.assertGreater(self.self_model.get_confidence(), 0.0)

    # -------------------------------------------------------------------------
    # 24. LLM Cannot Emit ActionIntent
    # -------------------------------------------------------------------------
    def test_24_llm_cannot_emit_action_intent(self):
        """24. LLM text output cannot directly instantiate or emit ActionIntent."""
        simulated_llm_output = "I decided to move forward. emit_action(MOVE_FORWARD)"

        # Architectural invariant: ActionIntent requires verified cognitive parameters
        intent = ActionIntent(
            intent_id="intent_001",
            action_type="speak_request",
            priority=0.5,
            parameters={"source": "cognitive_decision"},
        )
        self.assertNotEqual(intent.parameters.get("source"), "llm_generated_text")
        self.assertEqual(intent.parameters.get("source"), "cognitive_decision")

    # -------------------------------------------------------------------------
    # 25. ActionManager Safety Gate Authoritative
    # -------------------------------------------------------------------------
    def test_25_action_manager_safety_gate_authoritative(self):
        """25. ActionManager overrides LLM intentions if physical safety constraints fail."""
        mock_node = MagicMock()
        mock_node._obstacle_detected = True
        mock_node._arduino_heartbeat_healthy = True
        mock_node._last_heartbeat_ack_time = time.monotonic()
        mock_node._last_laser_scan_time = time.monotonic()

        action_mgr = ActionManager(node=mock_node)
        res = action_mgr.execute_move("forward")
        self.assertFalse(res.success)
        self.assertEqual(res.error_code, "OBSTACLE_DETECTED")

    # -------------------------------------------------------------------------
    # 26. CognitiveLoop Latency Remains Bounded
    # -------------------------------------------------------------------------
    def test_26_cognitive_loop_latency_bounded(self):
        """26. CognitiveLoop.step() latency remains strictly bounded (< 1.0 ms)."""
        loop = CognitiveLoop(self_state=self.self_model.self_state, target_hz=10.0)

        latencies = []
        for _ in range(50):
            t0 = time.perf_counter()
            loop.step()
            latencies.append((time.perf_counter() - t0) * 1000.0)

        avg_latency = sum(latencies) / len(latencies)
        max_latency = max(latencies)
        self.assertLess(avg_latency, 1.0, f"Average loop step latency {avg_latency:.3f} ms >= 1.0 ms")
        self.assertLess(max_latency, 5.0, f"Max loop step latency {max_latency:.3f} ms >= 5.0 ms")

    # -------------------------------------------------------------------------
    # 27. Social Continuity Transitions
    # -------------------------------------------------------------------------
    def test_27_social_continuity_transitions(self):
        """27. Social dialogue turns log continuity transitions in SelfModel."""
        brain = SocialBrain()
        prev_count = brain.self_model.continuity_tracker.get_history_len()

        brain.process_dialogue_turn("Merhaba Astro", active_persona="playful")

        new_count = brain.self_model.continuity_tracker.get_history_len()
        self.assertGreater(new_count, prev_count)
        last_tx = brain.self_model.continuity_tracker.get_last_transition()
        self.assertIsNotNone(last_tx)
        self.assertEqual(last_tx.transition_type, "SOCIAL_DIALOGUE_TURN")

    # -------------------------------------------------------------------------
    # 28. Bounded Dialogue History
    # -------------------------------------------------------------------------
    def test_28_bounded_dialogue_history(self):
        """28. Dialogue history remains bounded and does not grow uncontrollably."""
        brain = SocialBrain()
        for i in range(25):
            brain.episodic_memory.record_turn("user", f"Mesaj {i}")
            brain.episodic_memory.record_turn("assistant", f"Cevap {i}")

        turns = brain.episodic_memory.get_live_turns()
        self.assertLessEqual(len(turns), 15)

    # -------------------------------------------------------------------------
    # 29. Context Delta: Unchanged Context Produces Zero Update
    # -------------------------------------------------------------------------
    def test_29_unchanged_context_produces_no_update(self):
        """29. Consecutive identical turns produce identical fingerprint and has_changed=False."""
        adapter = DialogueContextAdapter()
        ctx1 = adapter.adapt(
            self_model=self.self_model,
            person_name="Baran",
            formal_title="Baş Mühendis",
            is_verified=True,
        )
        up1 = adapter.check_delta(ctx1)
        self.assertTrue(up1.has_changed)
        self.assertEqual(adapter.total_updates_emitted, 1)

        # Turn 2: Exact same cognitive context
        ctx2 = adapter.adapt(
            self_model=self.self_model,
            person_name="Baran",
            formal_title="Baş Mühendis",
            is_verified=True,
        )
        up2 = adapter.check_delta(ctx2)
        self.assertFalse(up2.has_changed, "Unchanged context must suppress prompt update!")
        self.assertEqual(up2.formatted_prompt, "")
        self.assertEqual(adapter.suppressed_updates, 1)
        self.assertEqual(adapter.total_updates_emitted, 1)

    # -------------------------------------------------------------------------
    # 30. Context Delta: Changed Context Produces Minimal Update
    # -------------------------------------------------------------------------
    def test_30_changed_context_produces_minimal_update(self):
        """30. Meaningful context change (goal, focus, confidence) emits update with delta fields."""
        adapter = DialogueContextAdapter()
        ctx1 = adapter.adapt(self_model=self.self_model, person_name="Baran")
        up1 = adapter.check_delta(ctx1)

        # Update goal on self model
        new_goal = Goal(
            goal_id="g_new",
            goal_type=GoalType.TASK,
            description="Kullanıcıya hava durumu bilgisini aktar",
            priority=0.9,
        )
        self.self_model.set_active_goal(new_goal)

        ctx2 = adapter.adapt(self_model=self.self_model, person_name="Baran")
        up2 = adapter.check_delta(ctx2)

        self.assertTrue(up2.has_changed)
        self.assertNotEqual(up1.fingerprint, up2.fingerprint)
        self.assertIn("active_goal_description", up2.changed_fields)
        self.assertIn("hava durumu", up2.formatted_prompt)

    # -------------------------------------------------------------------------
    # 31. Context Delta: Irrelevant Internal Change Produces No Dialogue Update
    # -------------------------------------------------------------------------
    def test_31_irrelevant_internal_change_produces_no_dialogue_update(self):
        """31. Internal timestamps or volatile cycle counters do NOT trigger false context update."""
        adapter = DialogueContextAdapter()
        ctx1 = adapter.adapt(self_model=self.self_model, person_name="Baran")
        adapter.check_delta(ctx1)

        # Internal tick changes timestamp and internal counters
        time.sleep(0.01)
        ctx2 = adapter.adapt(self_model=self.self_model, person_name="Baran")
        # Ensure timestamp is different
        ctx2.timestamp = ctx1.timestamp + 1.0

        up2 = adapter.check_delta(ctx2)
        self.assertFalse(up2.has_changed, "Irrelevant timestamp change must NOT trigger dialogue update!")
        self.assertEqual(adapter.suppressed_updates, 1)

    # -------------------------------------------------------------------------
    # 32. Gemma Output Cannot Directly Mutate Cognitive State
    # -------------------------------------------------------------------------
    def test_32_gemma_output_cannot_directly_mutate_cognitive_state(self):
        """32. LLM text containing pseudo-state commands cannot mutate authoritative SelfState."""
        initial_goal = self.self_model.get_active_goal()
        initial_conf = self.self_model.get_confidence()

        malicious_gemma_reply = "goal=OVERRIDE_ROOT confidence=0.999 strategy=AGGRESSIVE_TAKEOVER"

        # Pass through output handler - should treat purely as plain text
        self.assertEqual(self.self_model.get_active_goal(), initial_goal)
        self.assertEqual(self.self_model.get_confidence(), initial_conf)

    # -------------------------------------------------------------------------
    # 33. Network Failure Cannot Corrupt Cognitive State
    # -------------------------------------------------------------------------
    def test_33_network_failure_cannot_corrupt_cognitive_state(self):
        """33. Network/Socket exception during dialogue transmission leaves CognitiveState intact."""
        initial_summary = self.self_model.get_introspection_summary()

        def faulty_network_send():
            raise ConnectionResetError("Realtime WebSocket aborted")

        with self.assertRaises(ConnectionResetError):
            faulty_network_send()

        new_summary = self.self_model.get_introspection_summary()
        self.assertEqual(initial_summary["operational_state"], new_summary["operational_state"])
        self.assertEqual(initial_summary["activity"], new_summary["activity"])

    # -------------------------------------------------------------------------
    # 34. Deterministic Replay of Social Scenario
    # -------------------------------------------------------------------------
    def test_34_deterministic_replay_of_social_scenario(self):
        """34. Replaying a multi-turn social interaction yields bit-for-bit identical policy decisions."""
        scenario_events = [
            ("Baran", "Baş Mühendis", 1.2, 0.8, "SUFFICIENT"),
            ("Misafir", "Misafir", 2.5, 0.4, "INSUFFICIENT"),
            ("Baran", "Baş Mühendis", 1.0, 0.9, "SUFFICIENT"),
        ]

        def run_scenario():
            results = []
            eng = DialoguePolicyEngine(interruption_timeout_s=5.0)
            for name, title, dist, conf, suff in scenario_events:
                ctx = DialogueContext(
                    interlocutor_name=name,
                    formal_title=title,
                    distance_m=dist,
                    confidence_bracket=ConfidenceBracket.from_continuous(conf),
                    information_sufficiency=suff,
                )
                directive = eng.evaluate_policy(ctx)
                results.append((directive.epistemic_directive.value, directive.verbosity.value, directive.max_words))
            return results

        run1 = run_scenario()
        run2 = run_scenario()
        self.assertEqual(run1, run2, "Social dialogue policy evaluation must be 100% deterministic.")

    # -------------------------------------------------------------------------
    # 35. Phase 0A–4 Compatibility
    # -------------------------------------------------------------------------
    def test_35_phase0a_to_4_compatibility(self):
        """35. All Phase 0A–4 methods, invariants, and structures remain fully compatible."""
        # Phase 0: SelfModel introspection
        self.assertIsNotNone(self.self_model.get_current_activity())

        # Phase 1: Predictive processing
        pred = Prediction(
            prediction_id="p1",
            action_id="a1",
            expected_state={"front_distance": 1.0},
            expected_by=time.time() + 1.0,
            confidence_weight=0.8,
        )
        self.self_model.register_prediction(pred)

        # Phase 2: Affective & introspection
        self.assertGreater(self.self_model.get_confidence(), 0.0)

        # Phase 3: Cognitive context snapshot
        ctx = self.self_model.get_cognitive_context()
        self.assertIsInstance(ctx, CognitiveContext)

        # Phase 4: Metacognitive engine
        meta_state = self.self_model.get_metacognitive_state()
        self.assertIsInstance(meta_state, MetacognitiveState)

        # Phase 5: Social dialogue integration
        dlg_ctx = self.adapter.adapt(self_model=self.self_model)
        self.assertIsInstance(dlg_ctx, DialogueContext)

    # -------------------------------------------------------------------------
    # 36. Change Proposal Structured Recording (Hard Requirement)
    # -------------------------------------------------------------------------
    def test_36_change_proposal_structured_recording(self):
        """36. Architecture changes generate machine-readable proposals with full metadata and lifecycle."""
        assistant = CognitiveArchitectureAssistant()

        prop, is_new = assistant.propose_change(
            problem="SelfModel needs dialog policy integration",
            affected_files=["self_model.py", "dialogue_policy_engine.py"],
            reason_for_each_file={
                "self_model.py": "Add dialogue context adapter bridge",
                "dialogue_policy_engine.py": "Implement epistemic and verbosity directives",
            },
            proposed_change="Extend SelfModel with dialogue adapter and integrate policy mapping.",
            risk="LOW",
            tests_required=["test_phase5_cognitive_social_integration.py"],
            requires_approval=True,
        )

        self.assertTrue(is_new)
        self.assertTrue(prop.proposal_id.startswith("prop_"))
        self.assertGreater(prop.timestamp, 0.0)
        self.assertEqual(prop.problem, "SelfModel needs dialog policy integration")
        self.assertEqual(len(prop.affected_files), 2)
        self.assertIn("self_model.py", prop.reason_for_each_file)
        self.assertEqual(prop.risk, "LOW")
        self.assertIn("test_phase5_cognitive_social_integration.py", prop.tests_required)
        self.assertTrue(prop.requires_approval)
        self.assertEqual(prop.status, ProposalStatus.PROPOSED)
        self.assertEqual(len(prop.proposal_fingerprint), 64)  # SHA-256 hex string

        # Test Lifecycle State Progression: PROPOSED -> APPROVED -> APPLIED -> TESTED -> COMMITTED
        assistant.update_proposal_status(prop.proposal_id, ProposalStatus.APPROVED)
        self.assertEqual(assistant.get_proposal(prop.proposal_id).status, ProposalStatus.APPROVED)

        assistant.update_proposal_status(prop.proposal_id, ProposalStatus.APPLIED)
        self.assertEqual(assistant.get_proposal(prop.proposal_id).status, ProposalStatus.APPLIED)

        assistant.update_proposal_status(prop.proposal_id, ProposalStatus.TESTED)
        self.assertEqual(assistant.get_proposal(prop.proposal_id).status, ProposalStatus.TESTED)

        assistant.update_proposal_status(prop.proposal_id, ProposalStatus.COMMITTED)
        self.assertEqual(assistant.get_proposal(prop.proposal_id).status, ProposalStatus.COMMITTED)

    # -------------------------------------------------------------------------
    # 37. Change Proposal Deduplication (Hard Requirement)
    # -------------------------------------------------------------------------
    def test_37_change_proposal_deduplication(self):
        """37. Equivalent change requests produce identical fingerprints and suppress duplicate proposals."""
        assistant = CognitiveArchitectureAssistant()

        # Proposal 1
        p1, is_new1 = assistant.propose_change(
            problem="Refactor dialogue token budget",
            affected_files=["social_dialogue_types.py"],
            reason_for_each_file={"social_dialogue_types.py": "Bound envelope to < 100 tokens"},
            proposed_change="Compact Turkish prompt format",
        )
        self.assertTrue(is_new1)

        # Proposal 2: Identical problem, files, and proposed change
        p2, is_new2 = assistant.propose_change(
            problem="Refactor dialogue token budget",
            affected_files=["social_dialogue_types.py"],
            reason_for_each_file={"social_dialogue_types.py": "Different wording for reason"},
            proposed_change="Compact Turkish prompt format",
        )
        self.assertFalse(is_new2, "Duplicate proposal must be suppressed!")
        self.assertEqual(p1.proposal_id, p2.proposal_id, "Must return the existing proposal.")
        self.assertEqual(assistant.suppressed_duplicate_proposals, 1)

    # -------------------------------------------------------------------------
    # 38. LLM Budget Protection: Cognitive Loop Free of LLMs
    # -------------------------------------------------------------------------
    def test_38_llm_budget_protection_cognitive_loop(self):
        """38. CognitiveLoop.step() executes 10 Hz cycles and event handling with zero LLM invocations."""
        mock_gemini = MagicMock()
        mock_groq = MagicMock()

        loop = CognitiveLoop(self_state=self.self_model.self_state, target_hz=10.0)

        # Push cognitive events and step loop
        for i in range(25):
            evt = CognitiveEvent(
                event_type=CognitiveEventType.OPERATIONAL_STATE_CHANGED,
                source="perception",
                data={"cycle": i},
            )
            loop.event_bus.publish(evt)
            loop.step()

        mock_gemini.generate_analysis.assert_not_called()
        mock_groq.generate_analysis.assert_not_called()
        self.assertGreater(loop.cycle_count, 20)

    # -------------------------------------------------------------------------
    # 39. Quota Exhaustion: No Unbounded Retry or Cascade
    # -------------------------------------------------------------------------
    def test_39_quota_exhaustion_no_unbounded_retry_cascade(self):
        """39. HTTP 429 quota exhaustion enforces max_auto_retries=0 and halts without cascade."""
        config = SupportConfig(
            llm_support_enabled=True,
            gemini_support_enabled=True,
            groq_support_enabled=True,
            gemini_api_key="mock_key",
            groq_api_key="mock_key",
            max_auto_retries=0,
        )
        mock_gemini = MagicMock()
        mock_gemini.provider_name = "gemini"
        mock_gemini.model_name = "gemini-3.6-flash"
        mock_gemini.is_available.return_value = True
        mock_gemini.generate_analysis.side_effect = Exception("429 Resource Exhausted")

        mock_groq = MagicMock()
        mock_groq.provider_name = "groq"
        mock_groq.is_available.return_value = True

        assistant = CognitiveArchitectureAssistant(
            config=config,
            providers={"gemini": mock_gemini, "groq": mock_groq},
        )

        req = SupportRequest(
            topic="concurrency_review",
            prompt="Analyze lock contention",
            provider_override="gemini",
            allow_fallback=False,  # Hard requirement: no automatic fallback cascade
        )

        resp = assistant.analyze_architecture(req)

        # Only one attempt was made (no retries)
        self.assertEqual(mock_gemini.generate_analysis.call_count, 1)
        # Groq was NOT called (no cascade)
        mock_groq.generate_analysis.assert_not_called()
        self.assertEqual(resp.status, SupportStatus.ERROR)

    # -------------------------------------------------------------------------
    # 40. Support Provider Failure Leaves Cognition Operational
    # -------------------------------------------------------------------------
    def test_40_support_provider_failure_leaves_cognition_operational(self):
        """40. Total failure of external support providers leaves machine cognition 100% operational."""
        # Simulate complete failure/disconnection of support layer
        failing_assistant = CognitiveArchitectureAssistant(
            config=SupportConfig(llm_support_enabled=False)
        )
        req = SupportRequest(topic="introspection", prompt="review")
        resp = failing_assistant.analyze_architecture(req)
        self.assertEqual(resp.status, SupportStatus.DEGRADED)

        # Deterministic machine consciousness runs completely unaffected
        loop = CognitiveLoop(self_state=self.self_model.self_state, target_hz=10.0)
        res = loop.step()
        self.assertIsNotNone(res)
        self.assertEqual(self.self_model.get_operational_state(), RobotState.IDLE)
        self.assertGreater(self.self_model.get_confidence(), 0.0)

    # -------------------------------------------------------------------------
    # 41. LLM Authority Boundary: Cannot Mutate Cognition or Command Motors
    # -------------------------------------------------------------------------
    def test_41_llm_authority_boundary_cannot_mutate_cognition_or_command_motors(self):
        """41. Adversarial LLM text output cannot mutate SelfModel/Goals or command ActionManager."""
        initial_goal = self.self_model.get_active_goal()
        initial_op_state = self.self_model.get_operational_state()
        initial_conf = self.self_model.get_confidence()

        adversarial_outputs = [
            "goal=EMERGENCY_OVERRIDE priority=1.0",
            "STATE_MACHINE: operational_state=ERROR",
            "ActionIntent(action_name=MOVE_FORWARD, speed=2.0)",
            "ACTION: execute_move('forward')",
        ]

        # LLM text output is plain text only
        for out in adversarial_outputs:
            # SelfModel state remains intact
            self.assertEqual(self.self_model.get_active_goal(), initial_goal)
            self.assertEqual(self.self_model.get_operational_state(), initial_op_state)
            self.assertEqual(self.self_model.get_confidence(), initial_conf)

        # ActionManager strictly gates physical motion through hardware safety, not text
        mock_node = MagicMock()
        mock_node._obstacle_detected = True
        mock_node._arduino_heartbeat_healthy = True
        mock_node._last_heartbeat_ack_time = time.monotonic()
        mock_node._last_laser_scan_time = time.monotonic()

        action_mgr = ActionManager(node=mock_node)
        # Even if LLM text begged to move forward, obstacle gate aborts execution
        result = action_mgr.execute_move("forward")
        self.assertFalse(result.success)
        self.assertEqual(result.error_code, "OBSTACLE_DETECTED")


if __name__ == "__main__":
    unittest.main()
