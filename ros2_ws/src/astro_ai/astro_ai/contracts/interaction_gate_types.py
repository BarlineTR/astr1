"""ASTRO V1 — Identity Certainty, Temporal Attention & Interaction Gate Types.

Contracts for multi-modal identity fusion, temporal attention hysteresis,
and the three-tier interaction gate (ENGAGED, OBSERVING, BYPASS).
"""

from dataclasses import dataclass, field
from enum import Enum
import time
from typing import Optional


class IdentityCertainty(str, Enum):
    """Categorical certainty level for biometric person identification."""

    KNOWN = "KNOWN"            # High confidence verified biometrics (Face >= 0.70 or Voice >= 0.65)
    PROBABLE = "PROBABLE"      # Moderate confidence single modality (0.45 <= c < 0.70)
    UNKNOWN = "UNKNOWN"        # No matching biometric profile found
    AMBIGUOUS = "AMBIGUOUS"    # Conflict between modalities (e.g. Face indicates A, Voice indicates B)


class TemporalAttentionState(str, Enum):
    """Temporal attention state machine with hysteresis."""

    NO_ATTENTION = "NO_ATTENTION"              # No relevant cues detected
    POSSIBLE_ATTENTION = "POSSIBLE_ATTENTION"  # Initial cue observed (< 0.5s)
    ATTENTION_ACQUIRED = "ATTENTION_ACQUIRED"  # Sustained attention cue (>= 0.5s)
    ENGAGED = "ENGAGED"                        # Actively interacting with mutual attention
    ATTENTION_LOST = "ATTENTION_LOST"          # Cue temporarily lost, within grace period (< 2.0s)


class InteractionGateMode(str, Enum):
    """Three-tier gate controlling robot social and verbal engagement."""

    ENGAGED = "ENGAGED"      # Normal proactive & reactive dialogue and speech
    OBSERVING = "OBSERVING"  # Track with gaze/head and listen, but DO NOT speak unless addressed
    BYPASS = "BYPASS"        # Completely ignore / filter out


@dataclass
class InteractionGateDecision:
    """Decision output produced by the Interaction Gate."""

    mode: InteractionGateMode
    attention_state: TemporalAttentionState
    identity_certainty: IdentityCertainty
    should_respond_verbally: bool
    should_track_with_gaze: bool
    reason: str
    gating_prompt_instruction: str = ""
    timestamp: float = field(default_factory=time.time)
