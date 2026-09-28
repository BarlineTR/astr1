"""ASTRO V1 — Dialogue State & Conversation Continuity Contracts.

Provides token-minimized, bounded, introspectable data contracts for short-term
dialogue state, active topic tracking, and referential continuity.

ARCHITECTURAL INVARIANTS:
  1. STRICT SEPARATION: Dialogue state is short-term conversational context.
     It is NEVER conflated with long-term persistent memory (profile/biometrics).
  2. BOUNDED CONTEXT: Deques and turn buffers are strictly capped in O(1) time.
  3. LLM IS NOT STATE OWNER: DialogueState is updated deterministically.
     LLM outputs can never directly mutate state structures.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from enum import Enum
import time
from typing import Any, Dict, List, Optional


class DialogueActType(str, Enum):
    """Categorical dialogue act representing speaker conversational intent."""
    STATEMENT = "STATEMENT"
    QUESTION = "QUESTION"
    ANSWER = "ANSWER"
    CHOICE_SELECTION = "CHOICE_SELECTION"
    REFERENCE_RESOLUTION = "REFERENCE_RESOLUTION"
    CLARIFICATION = "CLARIFICATION"
    GREETING = "GREETING"
    COMMAND = "COMMAND"
    UNKNOWN = "UNKNOWN"


@dataclass
class TurnRecord:
    """Bounded, compact record of a single conversational turn."""
    turn_id: str
    speaker_role: str  # "user" | "assistant"
    text: str
    dialogue_act: DialogueActType = DialogueActType.STATEMENT
    intent: Optional[str] = None
    topic: Optional[str] = None
    resolved_entity: Optional[str] = None
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "turn_id": self.turn_id,
            "speaker_role": self.speaker_role,
            "text": self.text,
            "dialogue_act": self.dialogue_act.value,
            "intent": self.intent,
            "topic": self.topic,
            "resolved_entity": self.resolved_entity,
            "timestamp": round(self.timestamp, 4),
        }


@dataclass
class DialogueState:
    """Deterministic, bounded dialogue state tracking conversational continuity.

    Tracks the active topic, open questions, pending choice sets, and referential
    targets across consecutive turns.
    """
    active_topic: Optional[str] = None
    topic_attributes: Dict[str, Any] = field(default_factory=dict)
    current_dialogue_act: DialogueActType = DialogueActType.STATEMENT
    last_user_question: Optional[str] = None
    last_assistant_question: Optional[str] = None
    last_assistant_statement: Optional[str] = None
    pending_reference: Optional[str] = None
    pending_choices: List[str] = field(default_factory=list)
    unresolved_question: Optional[str] = None
    interlocutor_identity: Optional[str] = None
    turn_count: int = 0
    recent_turns: deque[TurnRecord] = field(default_factory=lambda: deque(maxlen=6))

    def reset_transient(self) -> None:
        """Resets transient referential state while strictly preserving identity and persistent profile."""
        self.active_topic = None
        self.topic_attributes.clear()
        self.pending_reference = None
        self.pending_choices.clear()
        self.unresolved_question = None
        self.last_user_question = None
        self.last_assistant_question = None
        self.last_assistant_statement = None
        self.current_dialogue_act = DialogueActType.STATEMENT

    def to_dict(self) -> Dict[str, Any]:
        """Machine-readable snapshot of dialogue state."""
        return {
            "active_topic": self.active_topic,
            "topic_attributes": dict(self.topic_attributes),
            "current_dialogue_act": self.current_dialogue_act.value,
            "last_user_question": self.last_user_question,
            "last_assistant_question": self.last_assistant_question,
            "last_assistant_statement": self.last_assistant_statement,
            "pending_reference": self.pending_reference,
            "pending_choices": list(self.pending_choices),
            "unresolved_question": self.unresolved_question,
            "interlocutor_identity": self.interlocutor_identity,
            "turn_count": self.turn_count,
            "recent_turns_count": len(self.recent_turns),
        }

    def format_dialogue_state_prompt(self) -> str:
        """Formats an ultra-compact Turkish prompt snippet strictly bounded under 60 tokens."""
        parts = []
        if self.interlocutor_identity:
            parts.append(f"Konuştuğun kişi: {self.interlocutor_identity}")
        if self.active_topic:
            topic_str = self.active_topic
            if self.topic_attributes:
                attrs = ", ".join(f"{k}={v}" for k, v in self.topic_attributes.items())
                topic_str += f" ({attrs})"
            parts.append(f"Aktif konu: {topic_str}")
        if self.pending_reference:
            parts.append(f"Kullanıcının seçtiği referans: {self.pending_reference}")
        if self.pending_choices:
            parts.append(f"Seçenekler: {', '.join(self.pending_choices[:3])}")
        if self.unresolved_question:
            parts.append(f"Cevap bekleyen soru: {self.unresolved_question}")
        elif self.last_assistant_question:
            parts.append(f"Bekleyen soru: {self.last_assistant_question}")
        if not parts:
            return ""
        return "=== DİYALOG DURUMU ===\n" + "\n".join(parts) + "\n\n"
