"""ASTRO V1 — Strategic Response Planner."""

from typing import Any, Dict, List

from astro_ai.contracts.intent_emotion_types import IntentType, RelationshipRole
from astro_ai.contracts.social_context import SocialContext, SocialDecision


class ResponsePlanner:
    """Formulates high-level social strategy directives before text generation."""

    @classmethod
    def plan_response_strategy(cls, context: SocialContext) -> SocialDecision:
        """Determines response strategy, tone, verbosity, and empathy parameters."""
        strategies: List[str] = []
        tone = "warm_and_natural"
        verbosity = "concise"
        humor = 0.3
        empathy = 0.5
        directness = 0.8

        # 1. Emotional Accommodation
        if context.user_valence < -0.3:
            strategies.append("Kullanıcının olumsuz/stresli duygusunu fark et ve empatik yaklaş")
            empathy = 0.9
            humor = 0.1
            tone = "supportive_and_gentle"

        # 2. Intent-Driven Strategy
        if context.user_intent == IntentType.GREETING:
            if context.relationship_role == RelationshipRole.CREATOR:
                strategies.append("Geliştiricin Baran'ı samimi, sadık ve neşeyle selamla")
                tone = "playful_and_enthusiastic"
            elif context.relationship_role == RelationshipRole.FRIEND:
                strategies.append(f"{context.person_name}'i eski bir dost gibi sıcak selamla")
            else:
                strategies.append("Yeni ziyaretçiyi nazik ve saygılı bir şekilde karşıla")

        elif context.user_intent == IntentType.MEMORY_QUERY:
            strategies.append("Belleğinde kayıtlı doğrulanmış bilgiyi net ve doğrudan aktar")
            directness = 0.95

        elif context.user_intent == IntentType.CORRECTION:
            strategies.append("Düzeltmeyi anlayışla kabul et ve bilginin güncellendiğini belirt")
            directness = 0.9

        elif context.user_intent == IntentType.QUESTION:
            strategies.append("Soruya net ve doğru yanıt ver; gereksiz gevezelikten kaçın")

        # 3. Contextual Memory Integration
        if context.relevant_memories:
            top_fact = context.relevant_memories[0]
            if top_fact.predicate not in ("verified_fact", "fact"):
                strategies.append(f"Uygunsa {top_fact.subject}'in {top_fact.predicate} ({top_fact.value}) bilgisini doğal şekilde sohbete bağla")

        return SocialDecision(
            should_speak=True,
            initiative_reason="dialogue_response",
            response_strategy=strategies,
            suggested_tone=tone,
            recommended_verbosity=verbosity,
            humor_level=humor,
            empathy_level=empathy,
            directness_level=directness,
            interruption_allowed=False,
        )
