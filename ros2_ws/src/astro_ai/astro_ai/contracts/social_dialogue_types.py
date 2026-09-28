"""ASTRO V1 — Social Dialogue Data Contracts & Policy Types (Phase 5).

Connects ASTRO's deterministic machine consciousness substrate to the
dialogue and social interaction layer via token-minimized, epistemically-grounded
data contracts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import hashlib
import json
import time
from typing import Any, Dict, List, Optional


class ConfidenceBracket(str, Enum):
    """Categorical confidence bracket derived from continuous confidence."""
    HIGH = "HIGH"          # >= 0.75
    MODERATE = "MODERATE"  # 0.45 <= c < 0.75
    LOW = "LOW"            # < 0.45

    @classmethod
    def from_continuous(cls, confidence: float) -> "ConfidenceBracket":
        c = float(confidence)
        if c >= 0.75:
            return cls.HIGH
        elif c >= 0.45:
            return cls.MODERATE
        return cls.LOW


class EpistemicDirective(str, Enum):
    """Directives governing factual assertion boundaries in dialogue."""
    FACTUAL = "FACTUAL"                      # Grounded assertion permitted
    QUALIFIED = "QUALIFIED"                  # Temporal or perceptual qualification required
    UNCERTAIN = "UNCERTAIN"                  # Explicit uncertainty or sensor contradiction required
    CLARIFY_OR_DECLINE = "CLARIFY_OR_DECLINE"# Clarification request or explicit 'bilmiyorum' required


class VerbosityLevel(str, Enum):
    """Target verbosity limits for spoken response generation."""
    CONCISE = "CONCISE"    # 10–15 words (high urgency, high frustration, safety warning)
    BALANCED = "BALANCED"  # 15–25 words (nominal conversation)
    DETAILED = "DETAILED"  # 25–40 words (curiosity, elaborate inquiry)


@dataclass
class DialogueDirective:
    """Actionable behavioral directives for dialogue expression."""
    epistemic_directive: EpistemicDirective = EpistemicDirective.FACTUAL
    verbosity: VerbosityLevel = VerbosityLevel.BALANCED
    max_words: int = 25
    clarification_needed: bool = False
    clarification_prompt: str = ""
    tone_guidance: str = "Doğal, samimi ve net"
    epistemic_guidance: str = "Bildiğin olgu ile tahmini daima ayırt et."
    safety_warning: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "epistemic_directive": self.epistemic_directive.value,
            "verbosity": self.verbosity.value,
            "max_words": self.max_words,
            "clarification_needed": self.clarification_needed,
            "clarification_prompt": self.clarification_prompt,
            "tone_guidance": self.tone_guidance,
            "epistemic_guidance": self.epistemic_guidance,
            "safety_warning": self.safety_warning,
        }


@dataclass
class DialogueContext:
    """Compact, token-minimized social-cognitive context snapshot.

    Contains ONLY the derived, necessary parameters for dialogue generation.
    Does NOT contain internal UUIDs, database blobs, or raw sensor arrays.
    """
    interlocutor_name: str = "Misafir"
    formal_title: str = "Misafir"
    is_verified: bool = False
    focused_person_id: Optional[str] = None
    current_activity: str = "Bilinmiyor"
    active_goal_description: Optional[str] = None
    confidence_bracket: ConfidenceBracket = ConfidenceBracket.MODERATE
    information_sufficiency: str = "SUFFICIENT"
    epistemic_limitation: str = "Görsel ya da hafıza bilgisi yoksa uydurma yapma; 'bilmiyorum' veya 'göremiyorum' de."
    distance_m: Optional[float] = None
    urgency_level: float = 0.0
    social_phase: str = "IDLE"
    active_conflicts: List[str] = field(default_factory=list)
    cognitive_decision_type: Optional[str] = None
    timestamp: float = field(default_factory=time.time)

    def compute_fingerprint(self) -> str:
        """Computes a deterministic SHA-256 fingerprint of dialogue-relevant fields.

        Excludes timestamp, volatile counters, or irrelevant internal metadata to
        prevent false positive updates across conversational turns.
        """
        canonical_payload = (
            self.interlocutor_name.strip().lower(),
            self.formal_title.strip().lower(),
            bool(self.is_verified),
            (self.focused_person_id or "").strip().lower(),
            self.current_activity.strip().lower(),
            (self.active_goal_description or "").strip().lower(),
            self.confidence_bracket.value,
            self.information_sufficiency.strip().upper(),
            round(self.distance_m, 1) if self.distance_m is not None else None,
            round(self.urgency_level, 1),
            self.social_phase.strip().upper(),
            tuple(sorted(self.active_conflicts)),
            (self.cognitive_decision_type or "").strip().upper(),
        )
        serialized = json.dumps(canonical_payload, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    def format_compact_prompt(self, directive: Optional[DialogueDirective] = None) -> str:
        """Formats an ultra-compact Turkish prompt snippet strictly bounded under 100 tokens."""
        dist_str = f"{self.distance_m:.1f}m" if self.distance_m is not None else "Bilinmiyor"
        verified_str = "Doğrulandı" if self.is_verified else "Doğrulanmadı"
        goal_str = self.active_goal_description or "Özel hedef yok"

        lines = [
            "[BİLİŞSEL DİYALOG BAĞLAMI]",
            f"- Muhatap: {self.interlocutor_name} ({self.formal_title}) | Durum: {verified_str} | Mesafe: {dist_str}",
            f"- Mevcut Durum / Odak: {self.current_activity}",
            f"- Bilişsel Hedef: {goal_str}",
            f"- Bilgi Durumu: {self.information_sufficiency} | Güven: {self.confidence_bracket.value}",
            f"- Epistemik Kural: {self.epistemic_limitation}",
        ]

        if directive:
            lines.append(
                f"- İletişim Direktifi: {directive.tone_guidance} | Max {directive.max_words} kelime | {directive.epistemic_guidance}"
            )
            if directive.safety_warning:
                lines.append(f"- GÜVENLİK UYARISI: {directive.safety_warning}")
            if directive.clarification_needed and directive.clarification_prompt:
                lines.append(f"- Netleştirme Gereksinimi: {directive.clarification_prompt}")

        return "\n".join(lines)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "interlocutor_name": self.interlocutor_name,
            "formal_title": self.formal_title,
            "is_verified": self.is_verified,
            "focused_person_id": self.focused_person_id,
            "current_activity": self.current_activity,
            "active_goal_description": self.active_goal_description,
            "confidence_bracket": self.confidence_bracket.value,
            "information_sufficiency": self.information_sufficiency,
            "epistemic_limitation": self.epistemic_limitation,
            "distance_m": self.distance_m,
            "urgency_level": self.urgency_level,
            "social_phase": self.social_phase,
            "active_conflicts": list(self.active_conflicts),
            "cognitive_decision_type": self.cognitive_decision_type,
            "fingerprint": self.compute_fingerprint(),
            "timestamp": self.timestamp,
        }


@dataclass
class DialogueContextUpdate:
    """Result of context change detection evaluation."""
    has_changed: bool
    fingerprint: str
    previous_fingerprint: Optional[str]
    changed_fields: List[str] = field(default_factory=list)
    formatted_prompt: str = ""
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "has_changed": self.has_changed,
            "fingerprint": self.fingerprint,
            "previous_fingerprint": self.previous_fingerprint,
            "changed_fields": list(self.changed_fields),
            "formatted_prompt": self.formatted_prompt,
            "timestamp": self.timestamp,
        }
