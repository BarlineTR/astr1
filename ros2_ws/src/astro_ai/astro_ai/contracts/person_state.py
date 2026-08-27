"""ASTRO V1 — Unified PersonState Data Contract."""

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from astro_ai.contracts.intent_emotion_types import EmotionSignal, RelationshipRole


@dataclass
class UnifiedPersonState:
    """Represents a fully fused, multi-sensory representation of an individual."""

    person_id: str
    name: str = "Misafir"
    formal_title: str = "Misafir"
    role: RelationshipRole = RelationshipRole.UNKNOWN
    is_known: bool = False
    identity_confidence: float = 0.0

    # Spatial State (Fused from OAK-D RGB-D + RPLiDAR)
    distance_m: float = 0.0
    azimuth_deg: float = 0.0  # -180 to +180 relative to robot front
    x_m: float = 0.0
    y_m: float = 0.0
    approach_velocity_mps: float = 0.0  # Positive = approaching, Negative = leaving
    is_present: bool = False

    # Visual & Gaze State
    is_looking_at_robot: bool = False
    gaze_dwell_s: float = 0.0
    visual_emotion: EmotionSignal = EmotionSignal.NEUTRAL
    visual_confidence: float = 0.0

    # Acoustic State
    is_speaking: bool = False
    audio_doa_deg: Optional[float] = None
    voice_match_confidence: float = 0.0
    estimated_gender: str = "unknown"

    # Social & Cognitive Attributes
    estimated_mood: str = "neutral"
    estimated_valence: float = 0.0  # -1.0 (very negative) to +1.0 (very positive)
    estimated_arousal: float = 0.0  # 0.0 (calm) to 1.0 (excited/agitated)
    engagement_score: float = 0.0  # 0.0 to 1.0
    familiarity_score: float = 0.0  # 0.0 to 1.0
    trust_score: float = 0.5  # 0.0 to 1.0

    # Tracking Metadata
    first_seen_ts: float = field(default_factory=time.time)
    last_seen_ts: float = field(default_factory=time.time)
    last_spoken_ts: float = 0.0
    interaction_turn_count: int = 0
    raw_attributes: Dict[str, Any] = field(default_factory=dict)
