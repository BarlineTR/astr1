"""ASTRO V1 — Master Social Brain Cognitive Orchestrator.

Integrates Perception, World Model, Self Model, Memory V2, Intent, Emotion,
Attention, Relationship Evolution, Social FSM, Initiative, and Response Planning.
"""

import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from astro_ai.brain.activity_episode import ActivityEpisodeTracker
from astro_ai.brain.adaptive_persona import AdaptivePersonaEngine
from astro_ai.brain.attention_manager import AttentionManager
from astro_ai.brain.dialogue_policy_engine import DialoguePolicyEngine
from astro_ai.brain.emotion_engine import EmotionEngine
from astro_ai.brain.initiative_engine import InitiativeEngine
from astro_ai.brain.interaction_gate import InteractionGate
from astro_ai.brain.intent_engine import IntentEngine
from astro_ai.brain.relationship_manager import RelationshipManager
from astro_ai.brain.response_planner import ResponsePlanner
from astro_ai.brain.self_model import SelfModel
from astro_ai.brain.social_initiative import SocialInitiativeManager
from astro_ai.contracts.adaptive_persona_types import AgeGroup
from astro_ai.brain.social_dialogue_adapter import DialogueContextAdapter
from astro_ai.brain.social_fsm import SocialFSM
from astro_ai.brain.world_model import WorldModel
from astro_ai.contracts.interaction_gate_types import (
    IdentityCertainty,
    InteractionGateDecision,
    InteractionGateMode,
    TemporalAttentionState,
)
from astro_ai.contracts.social_dialogue_types import DialogueContext, DialogueDirective
from astro_ai.contracts.intent_emotion_types import (
    ConversationPhase,
    EmotionSignal,
    IntentType,
    RelationshipRole,
)
from astro_ai.contracts.person_state import UnifiedPersonState
from astro_ai.contracts.social_context import SocialContext, SocialDecision
from astro_ai.memory_v2.autobiographical_memory import AutobiographicalMemory
from astro_ai.memory_v2.consolidation_engine import ConsolidationEngine
from astro_ai.memory_v2.episodic_memory import EpisodicMemoryV2
from astro_ai.memory_v2.migration import MemoryMigrator
from astro_ai.memory_v2.relationship_memory import RelationshipMemory
from astro_ai.memory_v2.retrieval_engine import MemoryRetrievalEngine
from astro_ai.memory_v2.semantic_memory import SemanticMemory
from astro_ai.memory_v2.spatial_memory import SpatialMemory
from astro_ai.memory_v2.sqlite_storage import SQLiteMemoryStorage
from astro_ai.spatial.spatial_fusion import SpatialFusionEngine


class SocialBrain:
    """Master Cognitive Engine for ASTRO Social Robot."""

    def __init__(
        self,
        db_path: Optional[str] = None,
        enable_migration: Optional[bool] = None,
        self_model: Optional[SelfModel] = None,
        world_model: Optional[WorldModel] = None,
        cognitive_loop: Optional[Any] = None,
    ):
        self._lock = threading.RLock()

        # 1. Epistemic & World Models (Shared single-self reference architecture)
        if cognitive_loop is not None:
            self.cognitive_loop = cognitive_loop
            self.self_model = SelfModel.from_cognitive_loop(cognitive_loop)
            self.world_model = cognitive_loop.world_model
        else:
            self.cognitive_loop = None
            self.self_model = self_model or SelfModel()
            self.world_model = world_model or WorldModel()

        # 2. Memory V2 Cognitive Architecture
        self.storage = SQLiteMemoryStorage(db_path)
        self.semantic_memory = SemanticMemory(self.storage)
        self.episodic_memory = EpisodicMemoryV2(self.storage)
        self.autobiographical_memory = AutobiographicalMemory(self.storage)
        self.spatial_memory = SpatialMemory(self.storage)
        self.relationship_memory = RelationshipMemory(self.storage)
        self.retrieval_engine = MemoryRetrievalEngine(self.storage, self.semantic_memory)
        self.consolidation_engine = ConsolidationEngine(
            self.semantic_memory, self.relationship_memory, self.episodic_memory
        )

        # Automatic Migration on Startup (only run on default persistent DB, not isolated test DBs)
        self.migrator = MemoryMigrator(
            self.storage, self.semantic_memory, self.relationship_memory, self.spatial_memory
        )
        if enable_migration is None:
            enable_migration = (db_path is None)
        if enable_migration:
            self.migrator.migrate_if_needed()

        # 3. Spatial & Sensory Fusion
        self.spatial_fusion = SpatialFusionEngine()

        # 4. Cognitive Reasoning Components
        self.intent_engine = IntentEngine()
        self.emotion_engine = EmotionEngine()
        self.attention_manager = AttentionManager()
        self.relationship_manager = RelationshipManager(self.relationship_memory)
        self.social_fsm = SocialFSM()
        self.initiative_engine = InitiativeEngine()
        self.response_planner = ResponsePlanner()
        self.dialogue_adapter = DialogueContextAdapter()
        self.dialogue_policy = DialoguePolicyEngine()
        self.interaction_gate = InteractionGate()
        self.episode_tracker = ActivityEpisodeTracker()
        self.adaptive_persona = AdaptivePersonaEngine()
        self.social_initiative = SocialInitiativeManager(compliment_cooldown_s=120.0)

    def bind_cognitive_loop(self, loop: Any) -> None:
        """Binds this SocialBrain to a live CognitiveLoop, sharing authoritative self and world models."""
        with self._lock:
            self.cognitive_loop = loop
            self.self_model.bind_cognitive_loop(loop)
            self.world_model = loop.world_model

    def process_dialogue_turn(
        self,
        user_text: str,
        person_state: Optional[UnifiedPersonState] = None,
        active_persona: str = "playful",
        acoustic_energy_rms: float = 500.0,
    ) -> Tuple[SocialContext, SocialDecision, str]:
        """Executes full cognitive reasoning loop for an incoming dialogue turn.

        Returns (SocialContext, SocialDecision, StructuredSystemPrompt).
        """
        with self._lock:
            # 1. Identity & Attention Resolution
            person = person_state or self.spatial_fusion.get_fused_primary_person()
            p_name = person.name if person else "Misafir"
            p_title = person.formal_title if person else "Misafir"
            is_looking = person.is_looking_at_robot if person else True
            distance_m = person.distance_m if person else 1.2

            # 2. Relationship Assessment
            rel_assessment = self.relationship_manager.assess_relationship(p_name, p_title)
            role = rel_assessment["role"]
            fam = rel_assessment["familiarity"]
            trust = rel_assessment["trust"]

            # 3. Intent & Emotion Classification
            intent, intent_conf = self.intent_engine.classify_intent(user_text)
            vis_emo = person.visual_emotion if person else EmotionSignal.NEUTRAL
            affect = self.emotion_engine.estimate_affect(
                visual_emotion=vis_emo,
                is_looking=is_looking,
                acoustic_energy_rms=acoustic_energy_rms,
            )

            # 4. Contextual Memory Retrieval
            relevant_mems = self.retrieval_engine.retrieve_relevant_memories(
                person_name=p_name,
                user_query=user_text,
                top_k=5,
            )

            # 5. Social FSM Transition
            phase = self.social_fsm.step(
                primary_person=person,
                is_user_speaking=True,
                is_robot_speaking=False,
                silence_duration_s=0.0,
            )

            # 6. Formulate Normalized Social Context with Epistemic Grounding (Camera = Eye)
            can_see = getattr(person, "can_claim_vision", True) if person else True
            in_cone = getattr(person, "in_optical_cone", True) if person else True

            if person and not can_see:
                if getattr(person, "has_audio", False) or getattr(person, "is_speaking", False):
                    epistemic_inst = (
                        "Kişi kameranın görüş alanı dışında ya da doğrudan görülmüyor. YALNIZCA SESİ DUYULUYOR. "
                        "Kişinin kıyafeti, yüzü, gözleri, yaşı veya görünüşü hakkında sahte görsel iddialarda bulunma. "
                        "Gerektiğinde 'Sesini duyuyorum ama şu an seni göremiyorum' gerçeğini belirt."
                    )
                else:
                    epistemic_inst = "Kişi kameranın görüş konisi dışında. Görsel iddia uydurma."
            elif person and can_see:
                epistemic_inst = "Kişi kameranın görüş konisi içinde doğrudan görülüyor ('Görüyorum')."
            else:
                epistemic_inst = "Görsel kanıt yok."

            # Episode tracking & continuity (Phase 4)
            episode = self.episode_tracker.update(person)
            pid = person.person_id if person else "person_guest"
            episode_guide = self.episode_tracker.get_continuity_guidance(pid)
            suppress_greet = self.episode_tracker.should_suppress_greeting(pid)
            is_reeng = bool(episode and episode.is_reengagement)

            clean_ut = user_text.lower()
            if any(w in clean_ut for w in ["merhaba", "selam", "günaydın", "iyi günler", "hey"]):
                self.episode_tracker.record_greeting(pid)
            self.episode_tracker.record_turn(pid, user_text)

            # Adaptive Persona & Demographic Reasoning (Phase 5)
            age_group, age_conf = self.adaptive_persona.estimate_age_group(person)
            persona_policy = self.adaptive_persona.evaluate_policy(active_persona, age_group)

            context = SocialContext(
                person_id=person.person_id if person else "person_guest",
                person_name=p_name,
                formal_title=p_title,
                relationship_role=role,
                familiarity=fam,
                trust=trust,
                conversation_phase=phase,
                user_intent=intent,
                user_mood=affect["primary_mood"],
                user_valence=affect["valence"],
                user_arousal=affect["arousal"],
                engagement_level=affect["engagement"],
                is_looking_at_robot=is_looking,
                distance_m=distance_m,
                relevant_memories=relevant_mems,
                active_persona=active_persona,
                can_claim_vision=can_see,
                in_optical_cone=in_cone,
                epistemic_instruction=epistemic_inst,
                episode_guidance=episode_guide,
                is_reengagement=is_reeng,
                suppress_greeting=suppress_greet,
                target_age_group=age_group.value,
                persona_adaptation_instruction=persona_policy.policy_prompt_instruction,
            )

            # 7. Cognitive & Metacognitive Integration (Phase 5)
            if person:
                self.self_model.self_state.focused_person_id = person.person_id
            self.dialogue_policy.handle_interlocutor_turn(
                person.person_id if person else None, p_name
            )

            meta_state, cog_decision = self.self_model.evaluate_cognition(
                perception_data={"person_distance": distance_m}
            )

            dialogue_ctx = self.dialogue_adapter.adapt(
                self_model=self.self_model,
                person_state=person,
                person_name=p_name,
                formal_title=p_title,
                distance_m=distance_m,
                social_phase=phase.value if hasattr(phase, "value") else str(phase),
                cognitive_decision=cog_decision,
            )
            dialogue_directive = self.dialogue_policy.evaluate_policy(
                dialogue_ctx,
                affective_state=self.self_model.affective_manager.state,
                cognitive_decision=cog_decision,
            )
            update_res = self.dialogue_adapter.check_delta(dialogue_ctx, directive=dialogue_directive)

            # 7.5 Identity Fusion, Temporal Attention & Interaction Gate (Phase 3)
            id_cert, canon_name = self.attention_manager.evaluate_identity_certainty(
                face_name=person.name if (person and person.has_vision) else None,
                face_confidence=person.visual_confidence if person else 0.0,
                voice_name=person.name if (person and person.has_audio) else None,
                voice_confidence=person.voice_match_confidence if person else 0.0,
            )
            has_cue = bool(person and (person.is_looking_at_robot or person.is_speaking or (user_text and len(user_text.strip()) > 0)))
            att_state = self.attention_manager.update_temporal_attention(has_cue)

            gate_decision = self.interaction_gate.evaluate(
                person=person,
                attention_state=att_state,
                identity_certainty=id_cert,
                user_text=user_text,
                is_quiet_mode=False,
            )

            # Social Initiative & Controlled Visual Compliments (Phase 6)
            compliment_dec = self.social_initiative.evaluate_visual_compliment(
                person=person,
                gate_mode=gate_decision.mode.value,
                age_group=age_group.value,
            )
            if compliment_dec.should_compliment:
                context.compliment_directive = compliment_dec.prompt_directive

            # 8. Formulate Strategic Decision
            decision = self.response_planner.plan_response_strategy(context)
            if persona_policy.effective_persona != active_persona:
                decision.suggested_tone = persona_policy.recommended_tone
            if compliment_dec.should_compliment:
                decision.response_strategy.append(compliment_dec.prompt_directive)
            decision.gate_mode = gate_decision.mode.value
            decision.gate_instruction = gate_decision.gating_prompt_instruction
            if not gate_decision.should_respond_verbally:
                decision.should_speak = False
                decision.initiative_reason = f"GATE_{gate_decision.mode.value}_{gate_decision.reason}"

            # 9. Construct Modular System Prompt
            prompt = self._build_modular_prompt(
                context, decision, user_text, dialogue_ctx=dialogue_ctx, dialogue_directive=dialogue_directive
            )

            # Record continuity in SelfModel
            self.self_model.continuity_tracker.record_transition(
                transition_type="SOCIAL_DIALOGUE_TURN",
                previous_value=None,
                new_value=p_name,
                cause="dialogue_turn",
                metadata={
                    "has_context_changed": update_res.has_changed,
                    "fingerprint": update_res.fingerprint,
                    "info_sufficiency": dialogue_ctx.information_sufficiency,
                },
            )

            # Record turn in episodic memory
            self.episodic_memory.record_turn("user", user_text)

            # Evolve relationship trust and familiarity
            if p_name and p_name.lower() != "misafir":
                self.relationship_manager.record_turn_interaction(p_name, valence=affect["valence"])

            return context, decision, prompt

    def _build_modular_prompt(
        self,
        context: SocialContext,
        decision: SocialDecision,
        user_text: str,
        dialogue_ctx: Optional[DialogueContext] = None,
        dialogue_directive: Optional[DialogueDirective] = None,
    ) -> str:
        """Constructs modularized system prompt without dumping unparsed database blobs."""
        parts = []

        # Part 1: Epistemic Self Model
        parts.append(self.self_model.get_self_description_prompt())

        # Part 1.5: Cognitive-to-Social Dialogue Envelope (Phase 5)
        if dialogue_ctx:
            parts.append(dialogue_ctx.format_compact_prompt(directive=dialogue_directive))

        # Part 2: Social Context & Interlocutor
        parts.append(
            f"=== ETKİLEŞİM VE SOSYAL BAĞLAM ===\n"
            f"- Muhatap: {context.person_name} ({context.formal_title})\n"
            f"- İlişki Durumu: {context.relationship_role.value} (Aşinalık: {context.familiarity:.2f}, Güven: {context.trust:.2f})\n"
            f"- Kullanıcı Niyeti: {context.user_intent.value}\n"
            f"- Kullanıcı Ruh Hali: {context.user_mood} (Valence: {context.user_valence}, Arousal: {context.user_arousal})\n"
            f"- Mesafe: {context.distance_m:.2f} metre, Bakış: {'Robota Bakıyor' if context.is_looking_at_robot else 'Başka Yere Bakıyor'}"
        )

        # Part 2.5: Epistemic Sensory Boundary (Camera = Eye)
        if getattr(context, "epistemic_instruction", ""):
            vis_claim_str = "AKTİF (Görülüyor)" if getattr(context, "can_claim_vision", True) else "YASAK (Yalnızca Ses/Radar)"
            cone_str = "Görüş Konisi İçinde" if getattr(context, "in_optical_cone", True) else "Görüş Konisi Dışında"
            parts.append(
                f"=== KAMERA = GÖZ (EPISTEMIK SINIR) ===\n"
                f"- Görsel İddia: {vis_claim_str}\n"
                f"- Kamera Görüş Konisi: {cone_str}\n"
                f"- Kural: {context.epistemic_instruction}"
            )

        # Part 2.6: Interaction Gate Directive (Phase 3)
        if getattr(decision, "gate_instruction", ""):
            parts.append(
                f"=== ETKİLEŞİM VE SÖZEL DİYALOG KAPISI ===\n"
                f"- Mod: {getattr(decision, 'gate_mode', 'ENGAGED')}\n"
                f"- Sözel Yanıt İzni: {'EVET' if getattr(decision, 'should_speak', True) else 'HAYIR (Sessiz Kal / Dinle)'}\n"
                f"- Kural: {decision.gate_instruction}"
            )

        # Part 2.7: Activity Episode Continuity (Phase 4)
        if getattr(context, "episode_guidance", ""):
            parts.append(f"=== AKTİVİTE OTURUMU VE SÜREKLİLİK ===\n{context.episode_guidance}")

        # Part 2.8: Adaptive Persona Directive (Phase 5)
        if getattr(context, "persona_adaptation_instruction", ""):
            parts.append(f"=== UYARLANABİLİR KİŞİLİK POLİTİKASI ===\n{context.persona_adaptation_instruction}")

        # Part 2.9: Social Initiative & Compliment Directive (Phase 6)
        if getattr(context, "compliment_directive", ""):
            parts.append(f"=== SOSYAL İNİSİYATİF VE İLTİFAT DİREKTİFİ ===\n{context.compliment_directive}")

        # Part 3: Relevant Retrieved Memories
        if context.relevant_memories:
            mem_lines = [
                f"- [{m.memory_type.value}] {m.subject} -> {m.predicate}: {m.value} (Güven: {m.confidence:.2f})"
                for m in context.relevant_memories
            ]
            parts.append("=== İLGİLİ HAFIZA BİLGİLERİ ===\n" + "\n".join(mem_lines))

        # Part 4: Strategic Response Directives
        if decision.response_strategy:
            strat_lines = [f"- {s}" for s in decision.response_strategy]
            parts.append(
                f"=== YANIT STRATEJİSİ VE TALİMATLAR ===\n"
                f"- Önerilen Ton: {decision.suggested_tone}\n"
                f"- Ayrıntı Seviyesi: {decision.recommended_verbosity}\n"
                + "\n".join(strat_lines)
            )

        return "\n\n".join(parts)
