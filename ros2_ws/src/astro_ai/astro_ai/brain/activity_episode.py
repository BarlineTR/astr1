"""ASTRO V1 — Activity Episode Tracker.

Preserves conversational continuity and suppresses repetitive greetings
across brief physical absences (e.g. user steps away for 10-30s and returns).
"""

import time
import uuid
from typing import Dict, List, Optional

from astro_ai.contracts.activity_episode_types import (
    ActivityEpisode,
    EpisodeState,
)
from astro_ai.contracts.person_state import UnifiedPersonState


class ActivityEpisodeTracker:
    """Manages conversational episode continuity and greeting repetition suppression."""

    def __init__(
        self,
        session_timeout_s: float = 60.0,
        reengagement_threshold_s: float = 8.0,
    ):
        self.session_timeout_s = session_timeout_s
        self.reengagement_threshold_s = reengagement_threshold_s
        self._episodes: Dict[str, ActivityEpisode] = {}
        self._current_episode_id: Optional[str] = None

    @property
    def current_episode(self) -> Optional[ActivityEpisode]:
        if self._current_episode_id and self._current_episode_id in self._episodes:
            return self._episodes[self._current_episode_id]
        return None

    def update(
        self,
        person: Optional[UnifiedPersonState],
        now: Optional[float] = None,
    ) -> Optional[ActivityEpisode]:
        """Updates episode lifecycle based on person presence and timestamps."""
        t = now if now is not None else time.time()

        # Check existing active episode for timeout expiration
        curr = self.current_episode
        if curr is not None:
            if curr.state == EpisodeState.PAUSED_ABSENCE:
                if curr.paused_time is not None and (t - curr.paused_time) > self.session_timeout_s:
                    curr.state = EpisodeState.EXPIRED
                    self._current_episode_id = None
                    curr = None

        # Case 1: No person present
        if person is None or not getattr(person, "is_present", True):
            if curr is not None and curr.state == EpisodeState.ACTIVE:
                curr.state = EpisodeState.PAUSED_ABSENCE
                curr.paused_time = t
                curr.is_reengagement = False
            return curr

        # Case 2: Person is present
        pid = person.person_id
        pname = person.name or "Misafir"

        if curr is not None and (curr.person_id == pid or curr.person_name.lower() == pname.lower()):
            if curr.state == EpisodeState.PAUSED_ABSENCE:
                absence_dur = (t - curr.paused_time) if curr.paused_time is not None else 0.0
                curr.state = EpisodeState.ACTIVE
                curr.paused_time = None
                curr.last_active_time = t
                if absence_dur >= self.reengagement_threshold_s:
                    curr.is_reengagement = True
                    curr.reengagement_count += 1
                else:
                    curr.is_reengagement = False
            else:
                curr.last_active_time = t
                curr.is_reengagement = False
            return curr

        # Case 3: Different person or new episode
        new_ep = ActivityEpisode(
            episode_id=f"ep_{uuid.uuid4().hex[:8]}",
            person_id=pid,
            person_name=pname,
            state=EpisodeState.ACTIVE,
            start_time=t,
            last_active_time=t,
            has_greeted=False,
            is_reengagement=False,
        )
        self._episodes[new_ep.episode_id] = new_ep
        self._current_episode_id = new_ep.episode_id
        return new_ep

    def record_turn(self, person_id: str, user_text: str, robot_text: str = "") -> None:
        """Records a completed turn in the episode."""
        curr = self.current_episode
        if curr is not None:
            curr.turn_count += 1
            curr.is_reengagement = False
            if robot_text:
                curr.recent_robot_phrases.append(robot_text.lower().strip())
                if len(curr.recent_robot_phrases) > 10:
                    curr.recent_robot_phrases = curr.recent_robot_phrases[-10:]

    def record_greeting(self, person_id: str) -> None:
        """Marks that greeting has already occurred in this episode."""
        curr = self.current_episode
        if curr is not None:
            curr.has_greeted = True
            curr.is_reengagement = False

    def should_suppress_greeting(self, person_id: str) -> bool:
        """Determines whether robotic greeting should be suppressed to prevent repetition."""
        curr = self.current_episode
        if curr is not None and curr.state == EpisodeState.ACTIVE:
            return curr.has_greeted
        return False

    def get_continuity_guidance(self, person_id: str) -> str:
        """Generates prompt guidance for conversational continuity."""
        curr = self.current_episode
        if curr is None:
            return "OTURUM: Yeni etkileşim oturumu. İlk selamlama yapılabilir."

        if curr.is_reengagement:
            return (
                f"OTURUM SÜREKLİLİĞİ [TEKRAR KATILIM]: {curr.person_name} kısa bir aradan sonra geri döndü "
                f"(Aynı oturum devam ediyor). 'Merhaba ben Astro' gibi sıfırdan tanışma YAPMA! "
                f"'Tekrar hoş geldin, devam edelim' veya doğrudan konuşulan konudan devam et."
            )

        if curr.has_greeted:
            return (
                f"OTURUM SÜREKLİLİĞİ [DEVAM EDEN SOHBET]: Bu oturumda {curr.person_name} zaten selamlandı. "
                "Cümleye 'Merhaba / Selam' diyerek papağan gibi başlama; doğrudan yanıta gir."
            )

        return "OTURUM: İlk temas. Doğal selamlama yapılabilir."
