"""ASTRO V1 — Social Context and Social Decision Data Contracts."""

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from astro_ai.contracts.intent_emotion_types import (
    ConversationPhase,
    EmotionSignal,
    IntentType,
    RelationshipRole,
)
from astro_ai.contracts.memory_models import MemoryRecord
from astro_ai.contracts.person_state import UnifiedPersonState


class SocialAction(str, Enum):
    """Authoritative semantic actions produced by the Social Brain."""
    ORIENT = "orient"
    OBSERVE = "observe"
    REMAIN_QUIET = "remain_quiet"
    ENGAGE = "engage"
    DIALOGUE_RESPONSE = "dialogue_response"


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

    # Epistemic Camera = Eye Sensory Fields
    can_claim_vision: bool = True
    in_optical_cone: bool = True
    epistemic_instruction: str = ""

    # Phase 4 Activity Episode Continuity Fields
    episode_guidance: str = ""
    is_reengagement: bool = False
    suppress_greeting: bool = False

    # Phase 5 Adaptive Persona Fields
    target_age_group: str = "UNKNOWN"
    persona_adaptation_instruction: str = ""

    # Phase 6 Social Initiative & Controlled Compliments
    compliment_directive: str = ""

    # Phase 7 Quiet/Sleep Social Awareness
    quiet_mode_active: bool = False
    quiet_awareness_directive: str = ""
    explicit_user_turn: bool = True

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
    gate_mode: str = "ENGAGED"
    gate_instruction: str = ""
    humor_level: float = 0.3               # 0.0 to 1.0
    empathy_level: float = 0.5             # 0.0 to 1.0
    directness_level: float = 0.7          # 0.0 to 1.0
    interruption_allowed: bool = False
    cooldown_s: float = 0.0
    action: SocialAction = SocialAction.OBSERVE
    directive: str = "observe"
