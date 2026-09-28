"""Forensic Fix 2 Test — Greeting Misclassification Resolution & Semantic Intent Mapping.

Verifies:
1. "ben şu anda ne yapıyorum?" -> ACTIVITY_QUERY (never GREETING)
2. "nasıl gidiyor hayat?" -> QUESTION
3. "ne haber?" -> SOCIAL_BID
4. "merhaba Astro" -> GREETING
5. All 4 inputs produce 4 distinct semantic intents.
6. Wake-word prefixes ("Astro ...") do not misclassify queries as GREETING.
7. SocialBrain integration produces correct context.user_intent and strategy.
"""

import unittest
from astro_ai.contracts.intent_emotion_types import IntentType, RelationshipRole, EmotionSignal
from astro_ai.brain.intent_engine import IntentEngine
from astro_ai.brain.social_brain import SocialBrain
from astro_ai.contracts.person_state import UnifiedPersonState


class TestForensicFix2GreetingMisclassification(unittest.TestCase):
    """Test suite ensuring accurate semantic intent classification and no false GREETINGs."""

    def test_four_distinct_semantic_intents(self):
        """The 4 specified test phrases MUST produce 4 distinct semantic intents."""
        t1 = "ben şu anda ne yapıyorum?"
        t2 = "nasıl gidiyor hayat?"
        t3 = "ne haber?"
        t4 = "merhaba Astro"

        i1, _ = IntentEngine.classify_intent(t1)
        i2, _ = IntentEngine.classify_intent(t2)
        i3, _ = IntentEngine.classify_intent(t3)
        i4, _ = IntentEngine.classify_intent(t4)

        self.assertEqual(i1, IntentType.ACTIVITY_QUERY, f"'{t1}' must be ACTIVITY_QUERY, got {i1}")
        self.assertEqual(i2, IntentType.QUESTION, f"'{t2}' must be QUESTION, got {i2}")
        self.assertEqual(i3, IntentType.SOCIAL_BID, f"'{t3}' must be SOCIAL_BID, got {i3}")
        self.assertEqual(i4, IntentType.GREETING, f"'{t4}' must be GREETING, got {i4}")

        # Assert all 4 are mutually distinct
        distinct_intents = {i1, i2, i3, i4}
        self.assertEqual(len(distinct_intents), 4, f"All 4 intents must be distinct, got {distinct_intents}")

    def test_wake_word_prefix_does_not_force_greeting(self):
        """Addressing the robot ('Astro ...') must NOT force GREETING for questions/queries."""
        queries = [
            ("Astro ben şu anda ne yapıyorum?", IntentType.ACTIVITY_QUERY),
            ("astro şu an ne yapıyorum", IntentType.ACTIVITY_QUERY),
            ("Astro ne yapıyorsun?", IntentType.ACTIVITY_QUERY),
            ("Astro nasıl gidiyor hayat?", IntentType.QUESTION),
            ("astro nasılsın?", IntentType.QUESTION),
            ("Astro ne haber?", IntentType.SOCIAL_BID),
            ("Astro beni duyuyor musun?", IntentType.QUESTION),
            ("Astro selam", IntentType.GREETING),
            ("Astro merhaba", IntentType.GREETING),
        ]

        for text, expected in queries:
            intent, _ = IntentEngine.classify_intent(text)
            self.assertEqual(intent, expected, f"Failed for '{text}': expected {expected}, got {intent}")

    def test_social_intent_regression_suite(self):
        """Verify the exact regression test set specified in the prompt."""
        cases = [
            ("merhaba Astro", IntentType.GREETING),
            ("nasılsın", IntentType.QUESTION),
            ("ben şu anda ne yapıyorum?", IntentType.ACTIVITY_QUERY),
            ("ne yapıyorsun?", IntentType.ACTIVITY_QUERY),
            ("sen beni görüyor musun?", IntentType.QUESTION),
        ]

        for text, expected in cases:
            intent, _ = IntentEngine.classify_intent(text)
            self.assertEqual(intent, expected, f"Regression failure for '{text}': expected {expected}, got {intent}")

    def test_social_brain_end_to_end_activity_query(self):
        """SocialBrain.process_dialogue_turn with activity query must produce ACTIVITY_QUERY context."""
        brain = SocialBrain(db_path=":memory:")
        person = UnifiedPersonState(
            person_id="person_baran",
            name="Baran",
            role=RelationshipRole.CREATOR,
            distance_m=1.0,
            is_looking_at_robot=True,
            can_claim_vision=True,
        )

        ctx, decision, prompt = brain.process_dialogue_turn(
            user_text="ben şu anda ne yapıyorum?",
            person_state=person,
            explicit_user_turn=True,
        )

        self.assertEqual(ctx.user_intent, IntentType.ACTIVITY_QUERY)
        self.assertIn("Kullanıcı Niyeti: ACTIVITY_QUERY", prompt)
        self.assertTrue(decision.should_speak)
        # Verify response strategy specifically addresses activity or contextual perception
        strategy_joined = " ".join(decision.response_strategy)
        self.assertIn("aktivite", strategy_joined.lower())


if __name__ == "__main__":
    unittest.main()
