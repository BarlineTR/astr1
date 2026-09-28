"""ASTRO V1 — Activity Episode Data Contracts.

Contracts for managing multi-turn conversational episodes across brief
absences, enforcing greeting repetition suppression and seamless re-engagement.
"""

from dataclasses import dataclass, field
from enum import Enum
import time
from typing import List, Optional


class EpisodeState(str, Enum):
    """Lifecycle state of an ongoing activity episode with an interlocutor."""

    ACTIVE = "ACTIVE"                  # Actively interacting, user present
    PAUSED_ABSENCE = "PAUSED_ABSENCE"  # User temporarily stepped away (< timeout)
    EXPIRED = "EXPIRED"                # Absence exceeded timeout (> 60s)
    COMPLETED = "COMPLETED"            # Interaction formally ended with farewell


@dataclass
class ActivityEpisode:
    """Represents a continuous interaction session across brief absences."""

    episode_id: str
    person_id: str
    person_name: str
    state: EpisodeState = EpisodeState.ACTIVE
    start_time: float = field(default_factory=time.time)
    last_active_time: float = field(default_factory=time.time)
    paused_time: Optional[float] = None
    turn_count: int = 0
    has_greeted: bool = False
    is_reengagement: bool = False
    reengagement_count: int = 0
    discussed_topics: List[str] = field(default_factory=list)
    recent_robot_phrases: List[str] = field(default_factory=list)
