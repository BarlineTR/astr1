"""ASTRO V1 — Memory V2 Data Models and Epistemic Representations."""

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from astro_ai.contracts.intent_emotion_types import MemorySourceType


class MemoryType(str, Enum):
    FACT = "FACT"
    OBSERVATION = "OBSERVATION"
    INFERENCE = "INFERENCE"


class MemoryConfidenceLevel(str, Enum):
    VERIFIED_FACT = "verified_fact"      # 0.95 - 1.00
    STRONG_EVIDENCE = "strong_evidence"  # 0.80 - 0.94
    BEHAVIORAL_INFERENCE = "behavioral_inference" # 0.60 - 0.79
    WEAK_INFERENCE = "weak_inference"    # 0.30 - 0.59
    UNRELIABLE = "unreliable"            # 0.00 - 0.29


@dataclass
class MemoryRecord:
    """Core structured memory record supporting epistemic confidence and contradiction tracking."""

    memory_id: str
    subject: str                      # e.g., "Baran", "Astro", "LivingRoom"
    predicate: str                    # e.g., "favorite_team", "creator", "location"
    value: str                        # e.g., "Bayern Munich", "True"
    memory_type: MemoryType = MemoryType.FACT
    source_type: MemorySourceType = MemorySourceType.EXPLICIT_USER_STATEMENT
    confidence: float = 1.0
    created_at: float = field(default_factory=time.time)
    last_confirmed_at: float = field(default_factory=time.time)
    last_used_at: float = 0.0
    use_count: int = 0
    evidence: str = ""
    visibility: str = "public"         # "public", "private", "owner_only"
    importance: float = 0.5            # 0.0 to 1.0
    expires_at: Optional[float] = None
    contradiction_status: str = "active" # "active", "superseded", "disputed"
    superseded_by_id: Optional[str] = None
    created_by_person: str = "system"


@dataclass
class AutobiographicalEvent:
    """Episodic memory of events the robot personally experienced."""

    event_id: str
    event_type: str                   # e.g., "first_meeting", "joint_debugging", "exhibition"
    title: str
    description: str
    participants: List[str] = field(default_factory=list)
    location: str = "Ahlat Selçuklu Teknoloji Alanı"
    timestamp: float = field(default_factory=time.time)
    emotional_valence: float = 0.0     # -1.0 to 1.0
    significance_score: float = 0.5   # 0.0 to 1.0


@dataclass
class SpatialMemoryItem:
    """Long-term representation of physical environmental landmarks and places."""

    item_id: str
    name: str                          # e.g., "charging_dock", "main_desk"
    category: str                      # "landmark", "furniture", "forbidden_zone"
    relative_x_m: float
    relative_y_m: float
    orientation_deg: float = 0.0
    description: str = ""
    confidence: float = 1.0
    last_verified_ts: float = field(default_factory=time.time)
