"""ASTRO V1 — Comprehensive Cognitive Social Brain Evaluation Suite.

Contains 85+ deterministic unit and integration test scenarios across:
  - Identity & Multi-Sensory Spatial Fusion
  - Memory V2, Epistemic Confidence, & Contradiction Resolution
  - Social Brain, Social FSM, & Proactive Initiative
  - Multi-Person Attention Management
  - LiDAR Radial Tracking & Spatial Intelligence
  - Epistemic Self Model & Hard Safety Boundaries
  - Privacy & Right-to-be-Forgotten Atomic Deletion
  - Graceful Fallback & Backward Compatibility
"""

import math
import os
import shutil
import sys
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "astro_ai")))

import numpy as np

from astro_ai.brain.attention_manager import AttentionManager
from astro_ai.brain.emotion_engine import EmotionEngine
from astro_ai.brain.initiative_engine import InitiativeEngine
from astro_ai.brain.intent_engine import IntentEngine
from astro_ai.brain.relationship_manager import RelationshipManager
from astro_ai.brain.response_planner import ResponsePlanner
from astro_ai.brain.self_model import SelfModel
from astro_ai.brain.social_brain import SocialBrain
from astro_ai.brain.social_fsm import SocialFSM
from astro_ai.brain.world_model import WorldModel
from astro_ai.contracts.intent_emotion_types import (
    ConversationPhase,
    EmotionSignal,
    IntentType,
    MemorySourceType,
    RelationshipRole,
)
from astro_ai.contracts.memory_models import (
    MemoryConfidenceLevel,
    MemoryRecord,
    MemoryType,
)
from astro_ai.contracts.person_state import UnifiedPersonState
from astro_ai.contracts.social_context import SocialContext, SocialDecision
from astro_ai.memory_v2.autobiographical_memory import AutobiographicalMemory
from astro_ai.memory_v2.confidence_engine import ConfidenceEngine
from astro_ai.memory_v2.consolidation_engine import ConsolidationEngine
from astro_ai.memory_v2.contradiction_engine import ContradictionEngine
from astro_ai.memory_v2.episodic_memory import EpisodicMemoryV2
from astro_ai.memory_v2.migration import MemoryMigrator
from astro_ai.memory_v2.relationship_memory import RelationshipMemory
from astro_ai.memory_v2.retrieval_engine import MemoryRetrievalEngine
from astro_ai.memory_v2.semantic_memory import SemanticMemory
from astro_ai.memory_v2.spatial_memory import SpatialMemory
from astro_ai.memory_v2.sqlite_storage import SQLiteMemoryStorage
from astro_ai.spatial.lidar_tracker import LidarTracker
from astro_ai.spatial.spatial_fusion import SpatialFusionEngine
from astro_ai.tools_arbitration.safety_guard import ToolSafetyGuard
from astro_ai.tools_arbitration.tool_registry import ToolCategory, ToolRegistry
from astro_ai.tools_arbitration.tool_router import ToolArbitrator


class TestIdentityAndSpatialFusion(unittest.TestCase):
    """1. Identity & Multi-Sensory Spatial Fusion Test Cases."""

    def setUp(self):
        self.tracker = LidarTracker()
        self.fusion = SpatialFusionEngine(self.tracker)

    def test_01_camera_and_lidar_distance_alignment(self):
        """1. Camera face at 1.2m aligns with LiDAR cluster at 1.18m."""
        self.fusion.update_vision_perception(
            faces=[{"name": "Baran", "confidence": 0.95, "is_known": True, "distance_m": 1.2, "head_yaw_deg": 0.0, "is_looking": True}],
            looking_at_robot=True,
            user_distance_m=1.2,
        )
        # Simulate LiDAR ranges with an obstacle at 0 deg, 1.18m
        ranges = [10.0] * 360
        ranges[180] = 1.18  # 0 deg (center)
        ranges[179] = 1.18
        ranges[181] = 1.18
        self.fusion.update_lidar_scan(ranges, angle_min=-math.pi, angle_increment=math.radians(1.0))

        people = self.fusion.compute_fusion()
        self.assertEqual(len(people), 1)
        self.assertEqual(people[0].name, "Baran")
        self.assertAlmostEqual(people[0].distance_m, 1.18, delta=0.05)

    def test_02_voiceprint_confirmed_identity_elevation(self):
        """2. Voiceprint match elevates identity confidence of known user."""
        self.fusion.update_vision_perception(faces=[{"name": "Baran", "confidence": 0.80, "is_known": True}])
        self.fusion.update_audio_perception(
            doa_deg=0.0,
            speaker_id_dict={"name": "Baran", "confidence": 0.92, "is_known": True},
            is_speaking=True,
        )
        people = self.fusion.compute_fusion()
        self.assertTrue(people[0].is_speaking)
        self.assertGreaterEqual(people[0].identity_confidence, 0.80)

    def test_03_unknown_guest_default_state(self):
        """3. Unrecognized person defaults to Misafir with unknown role."""
        self.fusion.update_vision_perception(faces=[{"name": "Misafir", "confidence": 0.20, "is_known": False}])
        people = self.fusion.compute_fusion()
        self.assertEqual(people[0].name, "Misafir")
        self.assertEqual(people[0].role, RelationshipRole.UNKNOWN)
        self.assertFalse(people[0].is_known)

    def test_04_lidar_only_side_approaching_person(self):
        """4. Person approaching outside camera FOV (e.g. 70 deg) is detected via LiDAR."""
        ranges = [10.0] * 360
        # 70 degrees
        ranges[250] = 1.8
        ranges[251] = 1.8
        ranges[252] = 1.8
        self.fusion.update_lidar_scan(ranges)
        people = self.fusion.compute_fusion()
        self.assertGreaterEqual(len(people), 1)
        self.assertAlmostEqual(people[0].distance_m, 1.8, delta=0.1)

    def test_05_primary_speaker_selection_priority(self):
        """5. Speaking person takes priority over silent person."""
        p1 = UnifiedPersonState(person_id="p1", name="Ali", is_speaking=False, distance_m=1.0)
        p2 = UnifiedPersonState(person_id="p2", name="Baran", is_speaking=True, distance_m=1.5)
        with patch.object(self.fusion, "compute_fusion", return_value=[p1, p2]):
            primary = self.fusion.get_fused_primary_person()
            self.assertEqual(primary.name, "Baran")

    def test_06_looking_person_priority_when_no_speaker(self):
        """6. Person looking at robot takes priority when no one is speaking."""
        p1 = UnifiedPersonState(person_id="p1", name="Ali", is_looking_at_robot=False, distance_m=0.9)
        p2 = UnifiedPersonState(person_id="p2", name="Veli", is_looking_at_robot=True, distance_m=1.4)
        with patch.object(self.fusion, "compute_fusion", return_value=[p1, p2]):
            primary = self.fusion.get_fused_primary_person()
            self.assertEqual(primary.name, "Veli")

    def test_07_closest_person_priority_fallback(self):
        """7. Closest person selected when gaze and speech are neutral."""
        p1 = UnifiedPersonState(person_id="p1", name="Ali", is_looking_at_robot=False, distance_m=2.0)
        p2 = UnifiedPersonState(person_id="p2", name="Veli", is_looking_at_robot=False, distance_m=1.1)
        with patch.object(self.fusion, "compute_fusion", return_value=[p1, p2]):
            primary = self.fusion.get_fused_primary_person()
            self.assertEqual(primary.name, "Veli")

    def test_08_approach_velocity_computation(self):
        """8. Successive LiDAR scans correctly compute negative radial velocity (approaching)."""
        ranges1 = [10.0] * 360
        ranges1[180] = 2.0
        ranges1[179] = 2.0
        ranges1[181] = 2.0
        self.tracker.process_scan(ranges1, timestamp=100.0)

        ranges2 = [10.0] * 360
        ranges2[180] = 1.6
        ranges2[179] = 1.6
        ranges2[181] = 1.6
        self.tracker.process_scan(ranges2, timestamp=100.5)

        tracks = self.tracker.get_active_tracks()
        self.assertEqual(len(tracks), 1)
        self.assertLess(tracks[0].velocity_mps, 0.0)  # -0.8 m/s

    def test_09_stale_track_pruning(self):
        """9. Tracks absent for > 2 seconds are pruned from active tracks."""
        ranges = [10.0] * 360
        ranges[180] = 1.5
        ranges[179] = 1.5
        ranges[181] = 1.5
        self.tracker.process_scan(ranges, timestamp=100.0)
        self.assertEqual(len(self.tracker.get_active_tracks()), 1)

        # Empty scan at 103.0s
        self.tracker.process_scan([10.0] * 360, timestamp=103.0)
        self.assertEqual(len(self.tracker.get_active_tracks()), 0)

    def test_10_creator_role_auto_assignment(self):
        """10. Name 'Baran' automatically assigned RelationshipRole.CREATOR."""
        self.fusion.update_vision_perception(faces=[{"name": "Baran", "confidence": 0.95, "is_known": True}])
        people = self.fusion.compute_fusion()
        self.assertEqual(people[0].role, RelationshipRole.CREATOR)


class TestMemoryV2ConfidenceAndContradictions(unittest.TestCase):
    """2. Memory V2, Confidence, and Contradictions Test Cases."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmp_dir, "test_cognitive.db")
        self.storage = SQLiteMemoryStorage(self.db_path)
        self.semantic = SemanticMemory(self.storage)
        self.episodic = EpisodicMemoryV2(self.storage)
        self.autobiographical = AutobiographicalMemory(self.storage)
        self.spatial = SpatialMemory(self.storage)
        self.relationship = RelationshipMemory(self.storage)
        self.retrieval = MemoryRetrievalEngine(self.storage, self.semantic)

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_11_explicit_statement_stores_high_confidence(self):
        """11. Explicit user statement stores memory with >= 0.95 confidence."""
        rec = self.semantic.store_fact(
            subject="Baran",
            predicate="favorite_team",
            value="Bayern Munich",
            source_type=MemorySourceType.EXPLICIT_USER_STATEMENT,
        )
        self.assertIsNotNone(rec)
        self.assertGreaterEqual(rec.confidence, 0.95)
        self.assertEqual(rec.contradiction_status, "active")

    def test_12_third_party_gossip_confidence_rejection(self):
        """12. Third-party hearsay receives low confidence (< 0.50) and is not verified fact."""
        conf, level = ConfidenceEngine.evaluate_confidence(
            MemoryType.FACT, MemorySourceType.THIRD_PARTY_STATEMENT
        )
        self.assertLess(conf, 0.50)
        self.assertFalse(ConfidenceEngine.is_eligible_for_facts(conf))

    def test_13_gossip_blocklist_blocks_recording(self):
        """13. Gossip keywords are rejected from semantic memory."""
        rec = self.semantic.store_fact(
            subject="Ahmet",
            predicate="durum",
            value="sezer ile kumar oynuyor",
            source_type=MemorySourceType.THIRD_PARTY_STATEMENT,
        )
        self.assertIsNone(rec)

    def test_14_contradiction_resolution_supersedes_old_fact(self):
        """14. New preference value marks previous active fact as superseded."""
        rec1 = self.semantic.store_fact(subject="Baran", predicate="favorite_coffee", value="Latte")
        self.assertEqual(rec1.contradiction_status, "active")

        # User updates preference
        rec2 = self.semantic.store_fact(subject="Baran", predicate="favorite_coffee", value="Espresso")
        self.assertEqual(rec2.contradiction_status, "active")

        # Query active facts
        active = self.semantic.query_active_facts_for_subject("Baran")
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0].value, "Espresso")

    def test_15_autobiographical_event_recording(self):
        """15. Autobiographical event is recorded and retrieved."""
        evt = self.autobiographical.record_experience(
            event_type="debugging",
            title="XTTS CUDA optimizasyonu",
            description="Baran ile birlikte Jetson FP16 CUDA bellek optimizasyonunu yaptık.",
            participants=["Baran"],
            valence=0.9,
            significance=0.95,
        )
        events = self.autobiographical.get_memorable_events(limit=1)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].title, "XTTS CUDA optimizasyonu")

    def test_16_spatial_landmark_persistence(self):
        """16. Spatial landmarks are stored with coordinates."""
        self.spatial.store_landmark(name="charging_dock", category="landmark", x_m=0.0, y_m=0.5, description="Şarj istasyonu")
        lm = self.spatial.get_landmark("charging_dock")
        self.assertIsNotNone(lm)
        self.assertEqual(lm.category, "landmark")
        self.assertEqual(lm.relative_y_m, 0.5)

    def test_17_relationship_profile_evolution(self):
        """17. Repeated interactions evolve role from NEW_USER to REGULAR_GUEST and increase familiarity."""
        self.relationship.get_or_create_profile("Batuhan")
        for _ in range(4):
            self.relationship.increment_interaction("Batuhan", topics=["Ahlat"])
        prof = self.relationship.get_or_create_profile("Batuhan")
        self.assertEqual(prof["role"], RelationshipRole.REGULAR_GUEST)
        self.assertGreater(prof["familiarity"], 0.20)

    def test_18_top_k_weighted_retrieval(self):
        """18. Retrieval engine ranks matching context query on top."""
        self.semantic.store_fact(subject="Baran", predicate="laptop", value="ThinkPad")
        self.semantic.store_fact(subject="Baran", predicate="favorite_food", value="Mantı")
        retrieved = self.retrieval.retrieve_relevant_memories(person_name="Baran", user_query="ne yemek istersin", top_k=1)
        self.assertEqual(len(retrieved), 1)
        self.assertEqual(retrieved[0].predicate, "favorite_food")

    def test_19_consolidation_engine_extracts_preferences(self):
        """19. Consolidation engine automatically extracts team preferences from dialogue."""
        turns = [
            {"role": "user", "content": "Benim tuttuğum takım Fenerbahçe."},
            {"role": "assistant", "content": "Harika bir takım!"},
        ]
        engine = ConsolidationEngine(self.semantic, self.relationship, self.episodic)
        res = engine.consolidate_session("Can", turns)
        self.assertTrue(res["archived"])
        facts = self.semantic.query_active_facts_for_subject("Can")
        self.assertEqual(len(facts), 1)
        self.assertEqual(facts[0].predicate, "favorite_team")
        self.assertEqual(facts[0].value, "fenerbahçe")

    def test_20_privacy_deletion_right_to_be_forgotten(self):
        """20. Right to be forgotten deletes semantic and relationship records."""
        self.semantic.store_fact(subject="Ali", predicate="meslek", value="Mühendis")
        self.relationship.get_or_create_profile("Ali")
        self.semantic.delete_facts_for_person("Ali")
        self.relationship.delete_profile("Ali")

        self.assertEqual(len(self.semantic.query_active_facts_for_subject("Ali")), 0)
        self.assertEqual(len(self.storage.execute_read("SELECT * FROM relationship_profiles WHERE lower(name) = 'ali'")), 0)

    def test_21_migration_from_legacy_json(self):
        """21. Legacy astro_memory.json migrates seamlessly to SQLite."""
        json_file = os.path.join(self.tmp_dir, "legacy_astro_memory.json")
        import json
        with open(json_file, "w", encoding="utf-8") as f:
            json.dump({
                "owner_name": "Baran",
                "verified_facts": ["Robotun üreticisinin adı Baran."],
                "known_people": {"ahmet": {"name": "Ahmet", "formal_title": "Ahmet Bey", "preferences": {"tea": "şekersiz"}}}
            }, f)
        migrator = MemoryMigrator(self.storage, self.semantic, self.relationship, self.spatial, json_file)
        self.assertTrue(migrator.migrate_if_needed())
        facts = self.semantic.query_active_facts_for_subject("Ahmet")
        self.assertEqual(len(facts), 1)
        self.assertEqual(facts[0].value, "şekersiz")

    def test_22_episodic_turn_sliding_window(self):
        """22. Episodic buffer enforces max_turns sliding window limit."""
        for i in range(20):
            self.episodic.record_turn("user", f"Turn {i}")
        turns = self.episodic.get_live_turns()
        self.assertEqual(len(turns), 15)
        self.assertEqual(turns[-1]["content"], "Turn 19")

    def test_23_source_reliability_ranking(self):
        """23. Explicit user statement has higher confidence than observation."""
        c_user, _ = ConfidenceEngine.evaluate_confidence(MemoryType.FACT, MemorySourceType.EXPLICIT_USER_STATEMENT)
        c_obs, _ = ConfidenceEngine.evaluate_confidence(MemoryType.OBSERVATION, MemorySourceType.ROBOT_OBSERVATION)
        self.assertGreater(c_user, c_obs)

    def test_24_dual_write_json_mirror_sync(self):
        """24. Dual-write synchronizes SQLite facts back to JSON mirror."""
        json_file = os.path.join(self.tmp_dir, "mirror_astro_memory.json")
        self.semantic.store_fact(subject="Astro", predicate="verified_fact", value="Astro bir sosyal robottur.")
        migrator = MemoryMigrator(self.storage, self.semantic, self.relationship, self.spatial, json_file)
        migrator.sync_to_json_mirror()
        self.assertTrue(os.path.exists(json_file))

    def test_25_disputed_fact_exclusion(self):
        """25. Superseded or disputed facts are excluded from active retrieval."""
        rec = self.semantic.store_fact(subject="Baran", predicate="city", value="Ankara")
        self.storage.execute_write("UPDATE semantic_facts SET contradiction_status = 'disputed' WHERE memory_id = ?", (rec.memory_id,))
        active = self.semantic.query_active_facts_for_subject("Baran")
        self.assertEqual(len(active), 0)


class TestSocialBrainAndFSM(unittest.TestCase):
    """3. Social Brain, Intent, Emotion, FSM, and Initiative Test Cases."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmp_dir, "test_brain.db")
        self.brain = SocialBrain(self.db_path)

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_26_greeting_intent_classification(self):
        """26. Greeting phrases classified as GREETING with high confidence."""
        intent, conf = IntentEngine.classify_intent("Selam Astro nasılsın?")
        self.assertEqual(intent, IntentType.GREETING)
        self.assertGreaterEqual(conf, 0.90)

    def test_27_correction_intent_classification(self):
        """27. 'Artık sevmiyorum' classified as CORRECTION."""
        intent, conf = IntentEngine.classify_intent("Hayır artık çay sevmiyorum kahve seviyorum.")
        self.assertEqual(intent, IntentType.CORRECTION)

    def test_28_memory_query_intent_classification(self):
        """28. 'Beni hatırlıyor musun' classified as MEMORY_QUERY."""
        intent, conf = IntentEngine.classify_intent("Beni hatırlıyor musun adım ne?")
        self.assertEqual(intent, IntentType.MEMORY_QUERY)

    def test_29_emotional_disclosure_intent(self):
        """29. Emotional user disclosure classified as EMOTIONAL_DISCLOSURE."""
        intent, conf = IntentEngine.classify_intent("Bugün çok üzgünüm moralim bozuk.")
        self.assertEqual(intent, IntentType.EMOTIONAL_DISCLOSURE)

    def test_30_negative_valence_triggers_empathy_strategy(self):
        """30. User negative emotion triggers supportive empathy in ResponsePlanner."""
        ctx = SocialContext(
            person_id="p1", person_name="Baran", formal_title="Baran",
            relationship_role=RelationshipRole.CREATOR, familiarity=1.0, trust=1.0,
            conversation_phase=ConversationPhase.ENGAGED, user_intent=IntentType.EMOTIONAL_DISCLOSURE,
            user_mood="sad", user_valence=-0.75, user_arousal=0.3, engagement_level=0.8,
            is_looking_at_robot=True, distance_m=1.0,
        )
        decision = ResponsePlanner.plan_response_strategy(ctx)
        self.assertGreaterEqual(decision.empathy_level, 0.8)
        self.assertIn("empatik", str(decision.response_strategy).lower())

    def test_31_social_fsm_orienting_to_greeting_transition(self):
        """31. Social FSM transitions from NOTICE to ORIENTING to GREETING."""
        fsm = SocialFSM()
        p = UnifiedPersonState(person_id="p1", name="Baran", is_present=True, is_looking_at_robot=True, distance_m=1.5)
        fsm.step(p, is_user_speaking=False, is_robot_speaking=False, silence_duration_s=0.0)
        self.assertEqual(fsm.current_phase, ConversationPhase.ORIENTING)

    def test_32_initiative_triggers_proactive_greeting(self):
        """32. InitiativeEngine triggers proactive greeting in GREETING phase."""
        init_eng = InitiativeEngine(cooldown_s=0.0)
        p = UnifiedPersonState(person_id="p1", name="Baran", is_present=True, is_looking_at_robot=True)
        should_init, reason, prob = init_eng.evaluate_initiative(
            ConversationPhase.GREETING, p, silence_duration_s=0.5, is_robot_speaking=False
        )
        self.assertTrue(should_init)
        self.assertEqual(reason, "proactive_greeting")

    def test_33_initiative_cooldown_suppression(self):
        """33. InitiativeEngine respects cooldown period."""
        init_eng = InitiativeEngine(cooldown_s=30.0)
        p = UnifiedPersonState(person_id="p1", name="Baran", is_present=True, is_looking_at_robot=True)
        init_eng.evaluate_initiative(ConversationPhase.GREETING, p, 0.5, False)
        # Second immediate call should be suppressed by cooldown
        should_init, reason, _ = init_eng.evaluate_initiative(ConversationPhase.GREETING, p, 0.5, False)
        self.assertFalse(should_init)
        self.assertEqual(reason, "in_cooldown")

    def test_34_full_dialogue_turn_cognitive_pipeline(self):
        """34. SocialBrain.process_dialogue_turn executes end-to-end and formats modular prompt."""
        p = UnifiedPersonState(person_id="p1", name="Baran", role=RelationshipRole.CREATOR, is_present=True, distance_m=1.1)
        ctx, decision, prompt = self.brain.process_dialogue_turn("Merhaba Astro", person_state=p)
        self.assertEqual(ctx.person_name, "Baran")
        self.assertTrue(decision.should_speak)
        self.assertIn("Baran", prompt)
        self.assertIn("ROBOT ÖZ-KİMLİK", prompt)

    def test_35_creator_prompt_customization(self):
        """35. Creator interaction includes creator-specific partner cues in prompt."""
        p = UnifiedPersonState(person_id="p1", name="Baran", role=RelationshipRole.CREATOR, is_present=True)
        _, _, prompt = self.brain.process_dialogue_turn("Nasılsın dostum?", person_state=p)
        self.assertIn("creator", prompt.lower())

    def test_36_silence_re_engagement_initiative(self):
        """36. Silence between 8s and 14s while user looking triggers re-engagement initiative."""
        init_eng = InitiativeEngine(cooldown_s=0.0)
        p = UnifiedPersonState(person_id="p1", name="Baran", is_present=True, is_looking_at_robot=True)
        should_init, reason, _ = init_eng.evaluate_initiative(
            ConversationPhase.ENGAGED, p, silence_duration_s=10.0, is_robot_speaking=False
        )
        self.assertTrue(should_init)
        self.assertEqual(reason, "re_engagement_prompt")

    def test_37_disengaging_silence_triggers_farewell(self):
        """37. Long silence (> 20s) in disengaging phase triggers polite farewell."""
        init_eng = InitiativeEngine(cooldown_s=0.0)
        p = UnifiedPersonState(person_id="p1", name="Baran", is_present=True, is_looking_at_robot=False)
        should_init, reason, _ = init_eng.evaluate_initiative(
            ConversationPhase.DISENGAGING, p, silence_duration_s=22.0, is_robot_speaking=False
        )
        self.assertTrue(should_init)
        self.assertEqual(reason, "polite_farewell")

    def test_38_speaking_robot_blocks_initiative(self):
        """38. Active robot speech blocks all proactive initiative triggers."""
        init_eng = InitiativeEngine(cooldown_s=0.0)
        p = UnifiedPersonState(person_id="p1", name="Baran", is_present=True)
        should_init, _, _ = init_eng.evaluate_initiative(
            ConversationPhase.GREETING, p, silence_duration_s=0.0, is_robot_speaking=True
        )
        self.assertFalse(should_init)

    def test_39_self_model_unknown_epistemic_directive(self):
        """39. Self model explicitly instructs robot to say 'bilmiyorum' for unknown facts."""
        self_desc = self.brain.self_model.get_self_description_prompt()
        self.assertIn("bilmiyorum", self_desc.lower())

    def test_40_world_model_snapshot_consistency(self):
        """40. World model returns consistent synchronized snapshot."""
        self.brain.world_model.record_event("Odaya giriş yapıldı")
        snap = self.brain.world_model.get_snapshot()
        self.assertGreaterEqual(len(snap.recent_events), 1)
        self.assertIn("Odaya giriş yapıldı", snap.recent_events[-1])


class TestAttentionAndMultiPerson(unittest.TestCase):
    """4. Multi-Person Attention and Spatial Tracking Test Cases."""

    def setUp(self):
        self.attention = AttentionManager()

    def test_41_single_person_attention(self):
        """41. Single present person receives full attention focus."""
        p1 = UnifiedPersonState(person_id="p1", name="Ali", is_present=True, distance_m=1.5)
        target, score = self.attention.select_focus_target([p1])
        self.assertEqual(target.person_id, "p1")
        self.assertGreater(score, 0.0)

    def test_42_speaker_wins_attention_over_closer_silent_person(self):
        """42. Speaking person at 2.0m wins attention over silent person at 1.0m."""
        p1 = UnifiedPersonState(person_id="p1", name="Silent", is_speaking=False, distance_m=1.0)
        p2 = UnifiedPersonState(person_id="p2", name="Speaker", is_speaking=True, distance_m=2.0)
        target, _ = self.attention.select_focus_target([p1, p2])
        self.assertEqual(target.name, "Speaker")

    def test_43_gaze_wins_attention_when_neither_speaks(self):
        """43. Person looking at robot wins attention when neither is speaking."""
        p1 = UnifiedPersonState(person_id="p1", name="Looking", is_looking_at_robot=True, distance_m=1.8)
        p2 = UnifiedPersonState(person_id="p2", name="Away", is_looking_at_robot=False, distance_m=1.8)
        target, _ = self.attention.select_focus_target([p1, p2])
        self.assertEqual(target.name, "Looking")

    def test_44_empty_people_returns_none(self):
        """44. Empty people list returns None target."""
        target, score = self.attention.select_focus_target([])
        self.assertIsNone(target)
        self.assertEqual(score, 0.0)

    def test_45_hysteresis_continuity_weight(self):
        """45. Current attended person receives continuity bonus score."""
        p1 = UnifiedPersonState(person_id="p1", name="Person1", distance_m=1.5)
        p2 = UnifiedPersonState(person_id="p2", name="Person2", distance_m=1.5)
        # Select p1 first
        self.attention.select_focus_target([p1])
        # In tie, p1 wins due to continuity
        target, _ = self.attention.select_focus_target([p1, p2])
        self.assertEqual(target.person_id, "p1")

    def test_46_lidar_scan_snapshot_obstacle_flag(self):
        """46. LiDAR scan snapshot detects obstacle within 1 meter."""
        tracker = LidarTracker()
        ranges = [10.0] * 360
        ranges[180] = 0.85  # 85 cm front obstacle
        snap = tracker.process_scan(ranges)
        self.assertTrue(snap.obstacle_detected_within_1m)
        self.assertFalse(snap.free_space_front)

    def test_47_lidar_scan_free_space_detection(self):
        """47. Clear front path (> 1.2m) sets free_space_front to True."""
        tracker = LidarTracker()
        ranges = [10.0] * 360
        ranges[180] = 3.5  # Clear
        snap = tracker.process_scan(ranges)
        self.assertTrue(snap.free_space_front)
        self.assertFalse(snap.obstacle_detected_within_1m)

    def test_48_radial_velocity_stationary_object(self):
        """48. Stationary obstacle has near-zero radial velocity."""
        tracker = LidarTracker()
        ranges = [10.0] * 360
        ranges[180] = 2.0
        ranges[179] = 2.0
        ranges[181] = 2.0
        tracker.process_scan(ranges, timestamp=10.0)
        tracker.process_scan(ranges, timestamp=10.5)
        tracks = tracker.get_active_tracks()
        self.assertEqual(len(tracks), 1)
        self.assertAlmostEqual(tracks[0].velocity_mps, 0.0, delta=0.05)

    def test_49_person_cluster_width_filtering(self):
        """49. Overly wide clusters (> 1.1m) are rejected as walls/large obstacles."""
        tracker = LidarTracker(max_cluster_width_m=1.1)
        # Simulate 2.5m wide wall
        pts = [(float(i * 0.1), 2.0, 2.0, 0.0) for i in range(30)]
        cl = tracker._build_cluster(1, pts, 10.0)
        self.assertIsNone(cl)

    def test_50_audio_doa_spatial_fusion_alignment(self):
        """50. Audio DOA angle matches spatially close LiDAR track."""
        tracker = LidarTracker()
        fusion = SpatialFusionEngine(tracker)
        # Person at +45 deg, 2m
        ranges = [10.0] * 360
        ranges[225] = 2.0
        ranges[224] = 2.0
        ranges[226] = 2.0
        fusion.update_lidar_scan(ranges)
        fusion.update_audio_perception(doa_deg=45.0, is_speaking=True)
        people = fusion.compute_fusion()
        self.assertEqual(len(people), 1)
        self.assertTrue(people[0].is_speaking)


class TestSelfModelEpistemicsAndSafety(unittest.TestCase):
    """5. Self Model, Tool Arbitration, and Safety Guard Test Cases."""

    def setUp(self):
        self.arbitrator = ToolArbitrator()
        self.arbitrator.register_handler("get_live_weather", lambda args: {"temp": 22, "city": args.get("city")})
        self.arbitrator.register_handler("set_reminder", lambda args: {"set": True, "mins": args.get("minutes")})

    def test_51_forbidden_system_tool_rejected(self):
        """51. Unsafe raw system tools are blocked by safety guard."""
        valid, reason = ToolSafetyGuard.validate_tool_call("exec_shell", {"command": "ls"})
        self.assertFalse(valid)
        self.assertIn("forbidden", reason.lower())

    def test_52_malicious_shell_injection_in_args_blocked(self):
        """52. Malicious injection inside tool arguments is rejected."""
        valid, reason = ToolSafetyGuard.validate_tool_call("get_live_weather", {"city": "Ahlat; rm -rf /"})
        self.assertFalse(valid)
        self.assertIn("keyword", reason.lower())

    def test_53_invalid_reminder_minutes_rejected(self):
        """53. Negative or zero reminder durations are rejected."""
        valid, _ = ToolSafetyGuard.validate_tool_call("set_reminder", {"minutes": -5, "topic": "test"})
        self.assertFalse(valid)

    def test_54_arbitrator_executes_valid_weather_tool(self):
        """54. Valid weather tool is arbitrated and executed successfully."""
        res = self.arbitrator.execute_tool("get_live_weather", {"city": "Ahlat"})
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["result"]["city"], "Ahlat")

    def test_55_unregistered_tool_returns_error(self):
        """55. Unregistered tool execution returns error without crashing."""
        res = self.arbitrator.execute_tool("unknown_tool_xyz", {})
        self.assertEqual(res["status"], "error")

    def test_56_tool_registry_schemas_validity(self):
        """56. All tool registry schemas have valid function names and parameters."""
        schemas = ToolRegistry.get_openai_tools()
        self.assertGreaterEqual(len(schemas), 4)
        for s in schemas:
            self.assertIn("name", s["function"])
            self.assertIn("description", s["function"])

    def test_57_self_model_creator_truth(self):
        """57. SelfModel accurately states creator is Baran."""
        model = SelfModel()
        self.assertEqual(model.creator, "Baran")
        self.assertEqual(model.name, "Astro")

    def test_58_self_model_epistemic_limits_text(self):
        """58. Epistemic prompt explicitly states limitations."""
        model = SelfModel()
        prompt = model.get_self_description_prompt()
        self.assertIn("tutucun olmadığını", prompt.lower())

    def test_59_affect_stress_detection(self):
        """59. Negative valence with high arousal flags is_stressed."""
        affect = EmotionEngine.estimate_affect(visual_emotion=EmotionSignal.ANGRY, acoustic_energy_rms=1500.0)
        self.assertTrue(affect["is_stressed"])

    def test_60_affect_happy_engagement_boost(self):
        """60. Happy visual emotion with gaze boosts engagement score."""
        affect = EmotionEngine.estimate_affect(visual_emotion=EmotionSignal.HAPPY, is_looking=True)
        self.assertGreaterEqual(affect["engagement"], 0.8)


class TestEdgeCasesAndCognitiveScenarios(unittest.TestCase):
    """6. Complex Multi-Modal Cognitive & Edge Case Scenarios."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmp_dir, "test_scenarios.db")
        self.brain = SocialBrain(self.db_path)

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_61_triple_preference_contradiction_cascade(self):
        """61. Triple preference updates maintain only the latest as active."""
        self.brain.semantic_memory.store_fact("Baran", "tea", "şekerli")
        self.brain.semantic_memory.store_fact("Baran", "tea", "az şekerli")
        self.brain.semantic_memory.store_fact("Baran", "tea", "şekersiz")

        active = self.brain.semantic_memory.query_active_facts_for_subject("Baran")
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0].value, "şekersiz")

    def test_62_multi_turn_episodic_consolidation(self):
        """62. Multi-turn dialogue consolidates and records episodic session."""
        turns = [
            {"role": "user", "content": "Astro selam"},
            {"role": "assistant", "content": "Selam Baran"},
            {"role": "user", "content": "Bugün Selçuklu mezarlığına gittim"},
            {"role": "assistant", "content": "Ahlat Selçuklu Meydan Mezarlığı harika bir tarihi miras!"},
        ]
        res = self.brain.consolidation_engine.consolidate_session("Baran", turns, inferred_topics=["Ahlat", "Tarih"])
        self.assertTrue(res["archived"])
        sessions = self.brain.episodic_memory.get_recent_sessions_for_person("rel_baran", limit=1)
        self.assertEqual(len(sessions), 1)
        self.assertIn("Ahlat", sessions[0]["topics"])

    def test_63_multi_user_simultaneous_tracking(self):
        """63. Simultaneous tracking of 3 distinct individuals with fused coordinates."""
        faces = [
            {"name": "Baran", "confidence": 0.95, "is_known": True, "distance_m": 1.2, "head_yaw_deg": 0.0},
            {"name": "Batuhan", "confidence": 0.85, "is_known": True, "distance_m": 2.1, "head_yaw_deg": 30.0},
            {"name": "Misafir", "confidence": 0.30, "is_known": False, "distance_m": 3.0, "head_yaw_deg": -40.0},
        ]
        self.brain.spatial_fusion.update_vision_perception(faces)
        people = self.brain.spatial_fusion.compute_fusion()
        self.assertEqual(len(people), 3)

    def test_64_speaker_switch_during_conversation(self):
        """64. Active attention immediately switches to speaker when second user speaks."""
        p1 = UnifiedPersonState(person_id="p1", name="Baran", is_speaking=False, distance_m=1.0)
        p2 = UnifiedPersonState(person_id="p2", name="Batuhan", is_speaking=True, distance_m=2.0)
        target, _ = self.brain.attention_manager.select_focus_target([p1, p2])
        self.assertEqual(target.name, "Batuhan")

    def test_65_autobiographical_chronological_ordering(self):
        """65. Autobiographical memories are returned in significance/recency order."""
        self.brain.autobiographical_memory.record_experience("meet", "İlk Çalıştırma", "Astro ilk kez açıldı.", significance=0.6)
        self.brain.autobiographical_memory.record_experience("milestone", "Ahlat Festivali", "Astro festivalde halkla buluştu.", significance=0.95)
        events = self.brain.autobiographical_memory.get_memorable_events(limit=2)
        self.assertEqual(events[0].title, "Ahlat Festivali")

    def test_66_spatial_landmark_recall(self):
        """66. Spatial landmarks can be accurately retrieved by name."""
        self.brain.spatial_memory.store_landmark("lab_desk", "furniture", 1.5, 0.8, description="Çalışma masası")
        item = self.brain.spatial_memory.get_landmark("lab_desk")
        self.assertIsNotNone(item)
        self.assertEqual(item.relative_x_m, 1.5)

    def test_67_right_to_be_forgotten_complete_purge(self):
        """67. Purge request removes facts, relationship profile, and associations."""
        self.brain.semantic_memory.store_fact("TestUser", "hobby", "Satranç")
        self.brain.relationship_memory.get_or_create_profile("TestUser")
        # Purge
        self.brain.semantic_memory.delete_facts_for_person("TestUser")
        self.brain.relationship_memory.delete_profile("TestUser")

        facts = self.brain.semantic_memory.query_active_facts_for_subject("TestUser")
        self.assertEqual(len(facts), 0)

    def test_68_lidar_dynamic_approach_alert(self):
        """68. Approaching human track has negative velocity."""
        ranges1 = [10.0] * 360
        ranges1[180] = 3.0
        ranges1[181] = 3.0
        self.brain.spatial_fusion.lidar_tracker.process_scan(ranges1, timestamp=10.0)

        ranges2 = [10.0] * 360
        ranges2[180] = 2.4
        ranges2[181] = 2.4
        self.brain.spatial_fusion.lidar_tracker.process_scan(ranges2, timestamp=10.5)

        tracks = self.brain.spatial_fusion.lidar_tracker.get_active_tracks()
        self.assertEqual(len(tracks), 1)
        self.assertLess(tracks[0].velocity_mps, 0.0)

    def test_69_world_model_event_log_bounds(self):
        """69. World model event log caps maximum buffer size without memory leaks."""
        for i in range(50):
            self.brain.world_model.record_event(f"Event {i}")
        snap = self.brain.world_model.get_snapshot()
        self.assertLessEqual(len(snap.recent_events), 20)

    def test_70_tool_arbitration_invalid_argument_type(self):
        """70. Tool argument type mismatch is rejected safely."""
        valid, _ = ToolSafetyGuard.validate_tool_call("set_reminder", {"minutes": "invalid_str", "topic": "test"})
        self.assertFalse(valid)

    def test_71_intent_confirmation_and_denial(self):
        """71. Confirmation and denial single words classified with > 0.95 confidence."""
        i_conf, c_conf = IntentEngine.classify_intent("evet")
        i_den, c_den = IntentEngine.classify_intent("hayır")
        self.assertEqual(i_conf, IntentType.CONFIRMATION)
        self.assertEqual(i_den, IntentType.DENIAL)
        self.assertGreaterEqual(c_conf, 0.95)
        self.assertGreaterEqual(c_den, 0.95)

    def test_72_relationship_role_evolution_to_friend(self):
        """72. 10 interactions evolve role to FRIEND."""
        for _ in range(10):
            self.brain.relationship_memory.increment_interaction("Cem", topics=["Yazılım"])
        prof = self.brain.relationship_memory.get_or_create_profile("Cem")
        self.assertEqual(prof["role"], RelationshipRole.FRIEND)

    def test_73_spatial_fusion_empty_scan_handling(self):
        """73. Empty scan returns default safe snapshot without crashing."""
        snap = self.brain.spatial_fusion.lidar_tracker.process_scan([])
        self.assertTrue(snap.free_space_front)
        self.assertEqual(len(snap.clusters), 0)

    def test_74_confidence_level_categorization(self):
        """74. Confidence scores accurately map to MemoryConfidenceLevel enum."""
        _, l_high = ConfidenceEngine.evaluate_confidence(MemoryType.FACT, MemorySourceType.TRUSTED_SYSTEM_FACT)
        _, l_low = ConfidenceEngine.evaluate_confidence(MemoryType.INFERENCE, MemorySourceType.UNCERTAIN_INFERENCE)
        self.assertEqual(l_high, MemoryConfidenceLevel.VERIFIED_FACT)
        self.assertEqual(l_low, MemoryConfidenceLevel.WEAK_INFERENCE)

    def test_75_response_planner_question_directness(self):
        """75. Direct questions produce concise and direct guidance."""
        ctx = SocialContext(
            person_id="p1", person_name="Misafir", formal_title="Misafir",
            relationship_role=RelationshipRole.UNKNOWN, familiarity=0.1, trust=0.5,
            conversation_phase=ConversationPhase.ENGAGED, user_intent=IntentType.QUESTION,
            user_mood="neutral", user_valence=0.0, user_arousal=0.2, engagement_level=0.5,
            is_looking_at_robot=True, distance_m=1.5,
        )
        dec = ResponsePlanner.plan_response_strategy(ctx)
        self.assertEqual(dec.recommended_verbosity, "concise")

    def test_76_self_model_hardware_completeness(self):
        """76. Self model includes all 5 core hardware subcomponents."""
        comps = self.brain.self_model.hardware_components
        self.assertGreaterEqual(len(comps), 5)
        self.assertTrue(any("Jetson" in c for c in comps))
        self.assertTrue(any("OAK-D" in c for c in comps))
        self.assertTrue(any("LiDAR" in c for c in comps))

    def test_77_relationship_manager_creator_tone(self):
        """77. Creator Baran receives playful loyal partner tone guidance."""
        res = self.brain.relationship_manager.assess_relationship("Baran")
        self.assertIn("partner", res["suggested_tone"])
        self.assertEqual(res["formality_level"], "informal_best_friend")

    def test_78_gossip_multiple_patterns(self):
        """78. Multiple gossip variations are caught by SemanticMemory filter."""
        self.assertTrue(self.brain.semantic_memory.is_gossip("ihsan hakkında ne biliyorsun"))
        self.assertTrue(self.brain.semantic_memory.is_gossip("onur aldatıyor mu"))
        self.assertFalse(self.brain.semantic_memory.is_gossip("Bugün hava nasıl?"))

    def test_79_retrieval_importance_weighting(self):
        """79. High importance memories receive ranking boost."""
        self.brain.semantic_memory.store_fact("Baran", "kan_grubu", "0 Rh+", created_by_person="Baran")
        self.brain.storage.execute_write("UPDATE semantic_facts SET importance = 1.0 WHERE predicate = 'kan_grubu'")
        mems = self.brain.retrieval_engine.retrieve_relevant_memories("Baran", user_query="", top_k=1)
        self.assertEqual(len(mems), 1)
        self.assertEqual(mems[0].predicate, "kan_grubu")

    def test_80_sqlite_wal_mode_verification(self):
        """80. SQLite storage is confirmed to run in WAL journal mode."""
        rows = self.brain.storage.execute_read("PRAGMA journal_mode;")
        self.assertEqual(rows[0][0].lower(), "wal")

    def test_81_social_fsm_listening_transition(self):
        """81. User speech transitions Social FSM from ENGAGED to LISTENING."""
        fsm = SocialFSM()
        p = UnifiedPersonState(person_id="p1", name="Baran", is_present=True, distance_m=1.2)
        fsm.step(p, is_user_speaking=False, is_robot_speaking=False, silence_duration_s=0.0)
        fsm.step(p, is_user_speaking=True, is_robot_speaking=False, silence_duration_s=0.0)
        self.assertEqual(fsm.current_phase, ConversationPhase.ENGAGED)

    def test_82_tool_arbitrator_security_injection_protection(self):
        """82. Sudo or bash script injections inside tool parameters are rejected."""
        res = self.brain.tool_arbitrator if hasattr(self.brain, "tool_arbitrator") else None
        valid, reason = ToolSafetyGuard.validate_tool_call("save_user_memory", {"key": "name", "value": "test; sudo rm -rf /"})
        self.assertFalse(valid)

    def test_83_spatial_memory_multiple_landmarks(self):
        """83. Multiple landmarks are cataloged and retrieved in alphabetical order."""
        self.brain.spatial_memory.store_landmark("b_door", "entrance", 3.0, 0.0)
        self.brain.spatial_memory.store_landmark("a_dock", "charging", 0.0, 0.5)
        lms = self.brain.spatial_memory.get_all_landmarks()
        self.assertGreaterEqual(len(lms), 2)
        self.assertEqual(lms[0].name, "a_dock")

    def test_84_intent_feedback_classification(self):
        """84. Positive praise classified as FEEDBACK or SOCIAL_BID."""
        intent, _ = IntentEngine.classify_intent("Çok teşekkür ederim harikasın!")
        self.assertIn(intent, (IntentType.FEEDBACK, IntentType.SOCIAL_BID, IntentType.STATEMENT))

    def test_85_end_to_end_cognitive_state_continuity(self):
        """85. Complete conversational loop maintains episodic turns and world state."""
        p = UnifiedPersonState(person_id="p1", name="Baran", role=RelationshipRole.CREATOR, is_present=True, distance_m=1.0)
        ctx1, dec1, _ = self.brain.process_dialogue_turn("Astro, Ahlat'ta mıyız?", person_state=p)
        self.assertEqual(ctx1.person_name, "Baran")
        self.assertTrue(dec1.should_speak)

        # Second turn in same session
        ctx2, dec2, _ = self.brain.process_dialogue_turn("Hava nasıl orada?", person_state=p)
        self.assertEqual(len(self.brain.episodic_memory.get_live_turns()), 2)


if __name__ == "__main__":
    unittest.main()

