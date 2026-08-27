"""ASTRO V1 — Social Relationship and Familiarity Manager."""

from typing import Any, Dict, Optional

from astro_ai.contracts.intent_emotion_types import RelationshipRole
from astro_ai.memory_v2.relationship_memory import RelationshipMemory


class RelationshipManager:
    """Evaluates interpersonal dynamics, trust, familiarity, and communication tone preferences."""

    def __init__(self, relationship_mem: RelationshipMemory):
        self.memory = relationship_mem

    def assess_relationship(self, person_name: str, formal_title: str = "") -> Dict[str, Any]:
        """Returns the current relationship assessment and conversational guidance for a person."""
        prof = self.memory.get_or_create_profile(person_name, formal_title)
        role = prof["role"]
        fam = prof["familiarity"]
        trust = prof["trust"]
        count = prof["interaction_count"]

        # Determine appropriate tone and formality
        if person_name.lower() == "baran":
            suggested_tone = "playful_and_loyal_partner"
            formality_level = "informal_best_friend"
        elif role == RelationshipRole.FRIEND or fam >= 0.70:
            suggested_tone = "warm_and_humorous"
            formality_level = "friendly_informal"
        elif role == RelationshipRole.REGULAR_GUEST:
            suggested_tone = "warm_and_respectful"
            formality_level = "semi_formal"
        else:
            suggested_tone = "polite_welcoming_and_helpful"
            formality_level = "polite_formal"

        return {
            "person_id": prof["person_id"],
            "name": prof["name"],
            "formal_title": prof["formal_title"],
            "role": role,
            "familiarity": fam,
            "trust": trust,
            "interaction_count": count,
            "suggested_tone": suggested_tone,
            "formality_level": formality_level,
            "shared_topics": prof["shared_topics"],
        }
