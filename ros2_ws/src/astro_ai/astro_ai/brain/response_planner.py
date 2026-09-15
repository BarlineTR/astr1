"""ASTRO V1 — Strategic Response Planner."""

from typing import Any, Dict, List

from astro_ai.contracts.intent_emotion_types import IntentType, RelationshipRole
from astro_ai.contracts.social_context import SocialAction, SocialContext, SocialDecision


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

        elif context.user_intent in (IntentType.QUESTION, IntentType.DIALOGUE_QUESTION):
            strategies.append("Soruya net ve doğru yanıt ver; gereksiz gevezelikten kaçın")

        elif context.user_intent in (IntentType.ACTIVITY_QUERY, IntentType.SELF_REFERENCE):
            strategies.append("Kullanıcının mevcut aktivitesi veya durumu hakkındaki görsel ve bağlamsal algını doğrudan açıkla")
            directness = 0.95

        elif context.user_intent == IntentType.SOCIAL_BID:
            strategies.append("Sosyal çağrıya samimi ve canlı bir karşılık ver")
            humor = 0.5

        # 3. Contextual Memory Integration
        if context.relevant_memories:
            top_fact = context.relevant_memories[0]
            if top_fact.predicate not in ("verified_fact", "fact"):
                strategies.append(f"Uygunsa {top_fact.subject}'in {top_fact.predicate} ({top_fact.value}) bilgisini doğal şekilde sohbete bağla")

        is_quiet = getattr(context, "quiet_mode_active", False)
        explicit_turn = getattr(context, "explicit_user_turn", True)

        action = SocialAction.DIALOGUE_RESPONSE if explicit_turn else (SocialAction.REMAIN_QUIET if is_quiet else SocialAction.OBSERVE)
        directive = "dialogue_response" if explicit_turn else ("remain_quiet" if is_quiet else "observe")
        reason = "dialogue_response" if explicit_turn else "PERCEPTION_STIMULUS_NO_USER_TURN"

        return SocialDecision(
            should_speak=bool(explicit_turn),
            initiative_reason=reason,
            response_strategy=strategies,
            suggested_tone=tone,
            recommended_verbosity=verbosity,
            humor_level=humor,
            empathy_level=empathy,
            directness_level=directness,
            interruption_allowed=False,
            action=action,
            directive=directive,
        )
