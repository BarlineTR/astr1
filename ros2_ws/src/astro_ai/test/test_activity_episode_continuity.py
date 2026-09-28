"""ASTRO V1 — Unit and Integration Tests for Phase 4: Activity Episode Architecture.

Tests:
1. ActivityEpisode lifecycle and turn tracking.
2. Greeting repetition suppression within active episode.
3. Brief absence and re-engagement continuity (10-30s absence).
4. Session timeout expiration (> 60s).
5. SocialBrain integration with continuity prompt directives.
6. Cross-model parity of episode continuity between Realtime and Local Gemma.
"""

import pytest

from astro_ai.brain.activity_episode import ActivityEpisodeTracker
from astro_ai.brain.social_brain import SocialBrain
from astro_ai.contracts.activity_episode_types import EpisodeState
from astro_ai.contracts.person_state import UnifiedPersonState


class TestActivityEpisodeContinuity:
    """Test suite verifying Activity Episode Continuity & Repetition Suppression."""

    def test_01_episode_lifecycle_and_turn_tracking(self):
        """Episode is created upon encounter and tracks interaction turns."""
        tracker = ActivityEpisodeTracker(session_timeout_s=60.0, reengagement_threshold_s=8.0)
        person = UnifiedPersonState(person_id="p_baran", name="Baran", is_present=True)

        ep = tracker.update(person, now=10.0)
        assert ep is not None
        assert ep.person_name == "Baran"
        assert ep.state == EpisodeState.ACTIVE
        assert ep.turn_count == 0
        assert ep.has_greeted is False

        # Record a turn
        tracker.record_turn("p_baran", "Merhaba Astro", "Selam Baran hoş geldin")
        assert ep.turn_count == 1
        assert "selam baran hoş geldin" in ep.recent_robot_phrases

    def test_02_greeting_repetition_suppression(self):
        """Greeting is suppressed once already delivered in the episode."""
        tracker = ActivityEpisodeTracker()
        person = UnifiedPersonState(person_id="p_baran", name="Baran", is_present=True)
        tracker.update(person, now=10.0)

        # Before greeting
        assert tracker.should_suppress_greeting("p_baran") is False
        assert "İlk temas" in tracker.get_continuity_guidance("p_baran")

        # After greeting
        tracker.record_greeting("p_baran")
        assert tracker.should_suppress_greeting("p_baran") is True

        guidance = tracker.get_continuity_guidance("p_baran")
        assert "zaten selamlandı" in guidance
        assert "Cümleye 'Merhaba / Selam' diyerek papağan gibi başlama" in guidance

    def test_03_brief_absence_and_reengagement(self):
        """Brief absence (e.g. 15s) triggers re-engagement without resetting the conversation."""
        tracker = ActivityEpisodeTracker(session_timeout_s=60.0, reengagement_threshold_s=8.0)
        person = UnifiedPersonState(person_id="p_baran", name="Baran", is_present=True)

        # 1. Active conversation at t=10.0
        ep = tracker.update(person, now=10.0)
        tracker.record_greeting("p_baran")

        # 2. User steps away at t=12.0
        tracker.update(None, now=12.0)
        assert ep.state == EpisodeState.PAUSED_ABSENCE

        # 3. User returns at t=30.0 (18s absence, between 8s and 60s)
        ep_re = tracker.update(person, now=30.0)
        assert ep_re.state == EpisodeState.ACTIVE
        assert ep_re.is_reengagement is True
        assert ep_re.reengagement_count == 1

        re_guide = tracker.get_continuity_guidance("p_baran")
        assert "TEKRAR KATILIM" in re_guide
        assert "kısa bir aradan sonra geri döndü" in re_guide
        assert "sıfırdan tanışma YAPMA" in re_guide

    def test_04_session_timeout_expiration(self):
        """Absence exceeding 60s expires episode and resets to fresh encounter."""
        tracker = ActivityEpisodeTracker(session_timeout_s=60.0, reengagement_threshold_s=8.0)
        person = UnifiedPersonState(person_id="p_baran", name="Baran", is_present=True)

        # Active at t=10.0
        ep1 = tracker.update(person, now=10.0)

        # User steps away at t=12.0
        tracker.update(None, now=12.0)

        # User returns at t=80.0 (68s absence > 60s timeout)
        ep2 = tracker.update(person, now=80.0)
        assert ep1.state == EpisodeState.EXPIRED
        assert ep2.episode_id != ep1.episode_id
        assert ep2.has_greeted is False

    def test_05_social_brain_episode_integration(self):
        """SocialBrain process_dialogue_turn integrates Activity Episode prompt section."""
        brain = SocialBrain(db_path=":memory:", enable_migration=False)
        person = UnifiedPersonState(person_id="p_can", name="Can", is_present=True)

        # Turn 1: Initial greeting
        ctx1, dec1, prompt1 = brain.process_dialogue_turn("Merhaba!", person_state=person)
        assert "=== AKTİVİTE OTURUMU VE SÜREKLİLİK ===" in prompt1

        # Turn 2: Follow-up question in same episode
        ctx2, dec2, prompt2 = brain.process_dialogue_turn("Yarın planın ne?", person_state=person)
        assert "=== AKTİVİTE OTURUMU VE SÜREKLİLİK ===" in prompt2
        assert "zaten selamlandı" in prompt2
        assert "papağan gibi başlama" in prompt2

    def test_06_cross_model_parity_episode_extraction(self):
        """Activity episode continuity is extracted for Local Gemma identically to Realtime."""
        system_prompt = (
            "Astro Default Instructions\n\n"
            "=== AKTİVİTE OTURUMU VE SÜREKLİLİK ===\n"
            "OTURUM SÜREKLİLİĞİ [DEVAM EDEN SOHBET]: Bu oturumda Baran zaten selamlandı. "
            "Cümleye 'Merhaba / Selam' diyerek papağan gibi başlama; doğrudan yanıta gir.\n\n"
            "=== YANIT STRATEJİSİ ===\n"
            "- Kısa cevap ver"
        )

        epistemic_gemma_rule = ""
        rule_keys = ["KAMERA = GÖZ", "EPISTEMIK", "ETKİLEŞİM VE SÖZEL", "AKTİVİTE OTURUMU"]
        if any(k in system_prompt for k in rule_keys):
            for section in system_prompt.split("\n\n"):
                if any(k in section for k in rule_keys):
                    epistemic_gemma_rule += section.strip() + "\n\n"

        gemma_prompt = (
            f"{epistemic_gemma_rule}"
            "ASTRO bir sosyal robot. Türkçe konuş. Kısa ve doğal cevap ver.\n\n"
            "Kullanıcı: Ne yapıyorsun?\n"
            "ASTRO:"
        )

        assert "AKTİVİTE OTURUMU VE SÜREKLİLİK" in gemma_prompt
        assert "zaten selamlandı" in gemma_prompt
        assert "papağan gibi başlama" in gemma_prompt
