"""ASTRO V1 — Social Context and Social Decision Data Contracts."""

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from astro_ai.contracts.intent_emotion_types import (
    ConversationPhase,
    EmotionSignal,
    IntentType,
    RelationshipRole,
)
from astro_ai.contracts.memory_models import MemoryRecord
from astro_ai.contracts.person_state import UnifiedPersonState


@dataclass
class SocialContext:
    """A normalized, holistic snapshot of the social situation at turn time."""

    person_id: str
    person_name: str
    formal_title: str
    relationship_role: RelationshipRole
    familiarity: float
    trust: float

    # Interaction & Conversational State
    conversation_phase: ConversationPhase
    user_intent: IntentType
    user_mood: str
    user_valence: float
    user_arousal: float
    engagement_level: float
    is_looking_at_robot: bool
    distance_m: float

    # Dialogue Continuity
    active_topic: Optional[str] = None
    recent_topics: List[str] = field(default_factory=list)
    turn_index: int = 0
    silence_duration_s: float = 0.0

    # Knowledge & Environmental Evidence
    relevant_memories: List[MemoryRecord] = field(default_factory=list)
    recent_events: List[str] = field(default_factory=list)
    environmental_cues: Dict[str, Any] = field(default_factory=dict)
    robot_current_state: str = "IDLE"
    active_persona: str = "playful"
    timestamp: float = field(default_factory=time.time)


@dataclass
class SocialDecision:
    """Strategic decision produced by the Social Brain to guide response generation."""

    should_speak: bool
    initiative_reason: str
    target_person: Optional[UnifiedPersonState] = None
    response_strategy: List[str] = field(default_factory=list)
    suggested_tone: str = "warm_and_natural"
    recommended_verbosity: str = "concise" # "concise", "moderate", "elaborate"
    humor_level: float = 0.3               # 0.0 to 1.0
    empathy_level: float = 0.5             # 0.0 to 1.0
    directness_level: float = 0.7          # 0.0 to 1.0
    interruption_allowed: bool = False
    cooldown_s: float = 0.0
