"""ASTRO V1 — Dialogue State Manager (Conversation Continuity Engine).

Maintains bounded dialogue state, active topic tracking, choice sets, and
deterministic referential resolution across consecutive conversational turns.

ARCHITECTURAL INVARIANTS:
  1. INDEPENDENT STATE OWNER: All state logic is encapsulated within this module.
     AstroRealtimeNode acts purely as orchestrator.
  2. DETERMINISTIC FIRST: Pronouns, ordinals, and meta-questions are resolved
     deterministically. Ambiguity yields UNKNOWN, which produces clarification.
  3. LLM IS NOT REFERENT SELECTOR: Never guess or fall back to random entities.
  4. MEMORY SEPARATION: Dialogue state is transient short-term context. It never
     mutates or conflates with long-term persistent memory (profile).
  5. TRANSIENT RESET SAFETY: reset_transient() clears only short-term referents;
     verified identity and persistent profile remain untouched.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from astro_ai.contracts.dialogue_state_types import (
    DialogueActType,
    DialogueState,
    TurnRecord,
)

_LOG = logging.getLogger(__name__)

CLARIFICATION_PROMPT = "Tam olarak hangisini kastettiğini anlayamadım; bir daha söyler misin?"


def tr_lower(text: str) -> str:
    """Turkish-aware lowercase that avoids the dotted-i Unicode bug."""
    if not text:
        return ""
    return text.replace("İ", "i").replace("I", "ı").lower().strip()


class DialogueStateManager:
    """Thread-safe, bounded manager for conversational continuity and referential resolution."""

    def __init__(self):
        self._lock = threading.RLock()
        self.state: DialogueState = DialogueState()

    def update_interlocutor(self, identity: Optional[str]) -> None:
        """Updates interlocutor identity without touching transient dialogue state."""
        with self._lock:
            if identity and str(identity).strip().lower() != "misafir":
                self.state.interlocutor_identity = str(identity).strip()
            else:
                self.state.interlocutor_identity = None

    def reset_transient(self) -> None:
        """Resets transient referential fields while strictly preserving identity."""
        with self._lock:
            self.state.reset_transient()

    def clear_all(self) -> None:
        """Full reset of dialogue state (e.g. session end)."""
        with self._lock:
            self.state = DialogueState()

    # ------------------------------------------------------------------
    # Deterministic Reference & Ordinal Resolution
    # ------------------------------------------------------------------

    def _resolve_ordinal(self, text: str) -> Optional[int]:
        """Detects ordinal choice references in Turkish (0-indexed)."""
        t = tr_lower(text)
        first_patterns = [
            r"\b(?:birinci|birincisi|birinciyi|birinciyi\s+seç|ilkini|ilk\s+olanı|1\.)\b",
            r"\bbirincisi\b",
            r"\bilkini\b",
        ]
        second_patterns = [
            r"\b(?:ikinci|ikincisi|ikincisini|ikinciyi|ikinci\s+olanı|2\.)\b",
            r"\bikinci\s+öneri(?:ni|nizi)?\b",
            r"\bikincisini\b",
            r"\bikinciyi\b",
        ]
        third_patterns = [
            r"\b(?:üçüncü|üçüncüsü|üçüncüsünü|üçüncüyü|3\.)\b",
            r"\büçüncü\s+öneri(?:ni|nizi)?\b",
        ]

        for p in first_patterns:
            if re.search(p, t):
                return 0
        for p in second_patterns:
            if re.search(p, t):
                return 1
        for p in third_patterns:
            if re.search(p, t):
                return 2
        return None

    def _is_deictic_pronoun_reference(self, text: str) -> bool:
        """Detects Turkish deictic pronouns referencing an active entity."""
        t = tr_lower(text)

        # Standalone "bu" or "o"
        if t in ("o", "bu", "o olsun", "bu olsun", "o lütfen", "bu lütfen"):
            return True

        patterns = [
            r"\b(?:onu|ondan|onunla)\b",
            r"\b(?:onun|bunun)\s+(?:hakkında|ile\s+ilgili)\b",
            r"\b(?:bunu|bundan|bununla)\b",
            r"\b(?:az\s+önce\s+söylediğin(?:i)?|demin\s+söylediğin(?:i)?)\s*(?:yap|anlat|açıkla)?\b",
        ]
        return any(re.search(p, t) for p in patterns)

    def _is_meta_question_assistant(self, text: str) -> Tuple[bool, bool]:
        """Detects user asking what the assistant recently asked or said.

        Returns (is_meta, is_question_mode).
        """
        t = tr_lower(text)
        if re.search(r"\b(?:sen\s+)?(?:az\s+önce|demin)?\s*(?:bana\s+)?ne\s+sormuştun\b", t):
            return True, True
        if (
            re.search(r"\b(?:sen\s+)?(?:az\s+önce|demin)?\s*(?:bana\s+)?ne\s+(?:demiştin|söyledin)\b", t)
            or "ne demiştin" in t
            or "ne söyledin" in t
        ):
            return True, False
        return False, False

    def _is_meta_question_user(self, text: str) -> bool:
        """Detects user asking what their own previous question was."""
        t = tr_lower(text)
        patterns = [
            r"\b(?:bir\s+önceki|önceki|az\s+önceki)\s+sorum\s+neydi\b",
            r"\bdaha\s+önce\s+(?:sana\s+)?ne\s+sormuştum\b",
            r"\baz\s+önce\s+(?:sana\s+)?ne\s+sormuştum\b",
        ]
        return any(re.search(p, t) for p in patterns)

    def _is_reiterating_question(self, text: str) -> bool:
        """Detects user reiterating an unresolved question ('ben sana onu soruyorum zaten')."""
        t = tr_lower(text)
        patterns = [
            r"\b(?:ben\s+)?sana\s+onu\s+soruyorum\s+zaten\b",
            r"\b(?:ben\s+)?onu\s+soruyorum\s+zaten\b",
            r"\b(?:ben\s+)?sana\s+onu\s+soruyorum\b",
            r"\bordan\s+bahsediyorum\b",
            r"\bondan\s+bahsediyorum\b",
        ]
        return any(re.search(p, t) for p in patterns)

    # ------------------------------------------------------------------
    # Deterministic Choice Extraction from Assistant Output
    # ------------------------------------------------------------------

    def _extract_deterministic_choices(self, text: str) -> List[str]:
        """Extracts choices ONLY when unambiguous deterministic evidence is present.

        Rule 3: pending_choices sadece deterministik olarak yeterli kanıt varsa
        oluşturulsun. Her assistant cümlesinden otomatik choice listesi çıkarma.
        Ambiguous durumda pending_choices oluşturma.
        """
        if not text or not text.strip():
            return []
        t = text.strip()

        # Pattern 1: Explicit binary question "A mı B mi?" / "A mı yoksa B mi?"
        # e.g. "Fenerbahçe mi Galatasaray mı?", "Çay mı kahve mi?"
        bin_m = re.search(
            r"([A-ZÇĞİÖŞÜa-zçğıöşü]+)\s+m[ıiIİuUüÜ]\s+(?:yoksa\s+)?([A-ZÇĞİÖŞÜa-zçğıöşü]+)\s+m[ıiIİuUüÜ]\b",
            t,
        )
        if bin_m:
            c1 = bin_m.group(1).strip()
            c2 = bin_m.group(2).strip()
            if c1.lower() != c2.lower():
                return [c1, c2]

        # Pattern 2: Explicit numbered list: "1. A ... 2. B" or "1) A ... 2) B"
        parts = re.split(r"(?:^|\s)(?:[1-9]\.|\([1-9]\)|[1-9]\))\s*", t)
        if len(parts) >= 3:
            cleaned = [p.strip().rstrip(".,;") for p in parts[1:] if p.strip()]
            if len(cleaned) >= 2:
                return cleaned

        return []

    # ------------------------------------------------------------------
    # Topic & Attribute Extraction
    # ------------------------------------------------------------------

    def _detect_topic_and_attributes(self, text: str) -> Tuple[Optional[str], Dict[str, Any]]:
        """Extracts active conversational topic and domain attributes."""
        t = tr_lower(text)
        topic = None
        attrs: Dict[str, Any] = {}

        # Known domain topics (with Turkish suffix flexibility)
        if re.search(r"\b(?:film\w*|sinema\w*|dizi\w*)\b", t):
            topic = "film"
        elif re.search(r"\b(?:hik[aâ]ye\w*|masal\w*|öykü\w*|roman\w*)\b", t):
            topic = "hikâye"
        elif re.search(r"\b(?:kitap\w*|yazar\w*)\b", t):
            topic = "kitap"
        elif re.search(r"\b(?:müzik\w*|şarkı\w*|parça\w*|albüm\w*)\b", t):
            topic = "müzik"
        elif re.search(r"\b(?:fenerbahçe\w*|galatasaray\w*|beşiktaş\w*|futbol\w*|maç\w*|takım\w*)\b", t):
            topic = "futbol"
        elif re.search(r"\b(?:hava\w*|yağmur\w*|kar\w*|sıcaklık\w*)\b", t):
            topic = "hava"

        # Genre / Style attributes
        genres = ["bilim kurgu", "komedi", "aksiyon", "dram", "korku", "macera", "polisiye", "fantastik", "belgesel"]
        for g in genres:
            if g in t:
                attrs["genre"] = g
                break

        return topic, attrs

    # ------------------------------------------------------------------
    # Turn Processing Interface
    # ------------------------------------------------------------------

    def process_user_turn(
        self,
        text: str,
        intent_name: Optional[str] = None,
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        """Processes user utterance through deterministic dialogue continuity logic.

        Returns:
            Tuple[is_deterministic_handled, response_or_resolved_text, resolution_type]
            - is_deterministic_handled: If True, AstroRealtimeNode can synthesize and respond
              directly with 0ms LLM overhead (meta-questions, clarifications).
            - response_or_resolved_text: The deterministic reply string, or resolved referent name.
            - resolution_type: Machine-readable label ('meta_history', 'clarification', 'choice_resolved', etc.).
        """
        with self._lock:
            if not text or not text.strip():
                return False, None, None

            raw_text = text.strip()
            self.state.turn_count += 1
            t_now = time.time()

            # Track domain user questions (excluding meta-questions)
            is_q = (
                raw_text.endswith("?")
                or any(w in tr_lower(raw_text).split() for w in ["mı", "mi", "mu", "mü", "nasıl", "neden", "ne", "nerede", "hangisi", "kim", "kimin", "kaç"])
            )
            is_meta_ast = self._is_meta_question_assistant(raw_text)[0]
            is_meta_usr = self._is_meta_question_user(raw_text)

            if is_q and not is_meta_ast and not is_meta_usr:
                self.state.last_user_question = raw_text
                self.state.unresolved_question = raw_text
                self.state.current_dialogue_act = DialogueActType.QUESTION

            # 1. Meta-Question: What did the assistant ask/say?
            is_meta_ast, is_ask_q = self._is_meta_question_assistant(raw_text)
            if is_meta_ast:
                if is_ask_q:
                    if self.state.last_assistant_question:
                        rep = f"Az önce sana şunu sormuştum: {self.state.last_assistant_question}"
                    else:
                        rep = "Az önce henüz sana bir soru sormamıştım."
                else:
                    if self.state.last_assistant_statement:
                        rep = f"Az önce şunu söylemiştim: {self.state.last_assistant_statement}"
                    else:
                        rep = "Az önce henüz bir şey söylememiştim."
                self._record_turn(raw_text, "user", DialogueActType.QUESTION, intent=intent_name)
                return True, rep, "meta_history_assistant"

            # 2. Meta-Question: What did the user ask previously?
            if self._is_meta_question_user(raw_text):
                if self.state.last_user_question:
                    rep = f"Bir önceki sorun şuydu: {self.state.last_user_question}"
                else:
                    rep = "Daha önce bana henüz bir soru sormamıştın."
                self._record_turn(raw_text, "user", DialogueActType.QUESTION, intent=intent_name)
                return True, rep, "meta_history_user"

            # 3. Reiterating question ("Ben sana onu soruyorum zaten")
            if self._is_reiterating_question(raw_text):
                ref_q = self.state.unresolved_question or self.state.last_user_question
                if ref_q:
                    rep = f"Anladım, bana {ref_q!r} sorunu hatırlatıyorsun. Hemen yanıtlayayım."
                    self._record_turn(raw_text, "user", DialogueActType.STATEMENT, intent=intent_name)
                    return True, rep, "reiterate_question"
                else:
                    self._record_turn(raw_text, "user", DialogueActType.CLARIFICATION, intent=intent_name)
                    return True, CLARIFICATION_PROMPT, "clarification"

            # 4. Ordinal Choice Resolution ("ikincisi", "birincisi", "2.")
            ord_idx = self._resolve_ordinal(raw_text)
            if ord_idx is not None:
                if self.state.pending_choices and len(self.state.pending_choices) > ord_idx:
                    selected = self.state.pending_choices[ord_idx]
                    self.state.pending_reference = selected
                    self.state.current_dialogue_act = DialogueActType.CHOICE_SELECTION
                    self._record_turn(
                        raw_text, "user", DialogueActType.CHOICE_SELECTION,
                        intent=intent_name, resolved=selected,
                    )
                    # Not handled deterministically if conversation continues, but resolved entity is recorded
                    return False, selected, "choice_resolved"
                else:
                    # Ambiguity! Rule 4: ambiguity => UNKNOWN => clarification
                    self._record_turn(raw_text, "user", DialogueActType.CLARIFICATION, intent=intent_name)
                    return True, CLARIFICATION_PROMPT, "clarification"

            # 5. Deictic / Pronoun Reference ("onu", "o", "ondan", "onun hakkında anlat")
            if self._is_deictic_pronoun_reference(raw_text):
                if self.state.pending_reference:
                    ref = self.state.pending_reference
                    self.state.current_dialogue_act = DialogueActType.REFERENCE_RESOLUTION
                    self._record_turn(
                        raw_text, "user", DialogueActType.REFERENCE_RESOLUTION,
                        intent=intent_name, resolved=ref,
                    )
                    return False, ref, "reference_resolved"
                else:
                    # Ambiguity! Rule 4: ambiguity => UNKNOWN => clarification
                    self._record_turn(raw_text, "user", DialogueActType.CLARIFICATION, intent=intent_name)
                    return True, CLARIFICATION_PROMPT, "clarification"

            # 6. Topic and Attribute Tracking
            detected_topic, detected_attrs = self._detect_topic_and_attributes(raw_text)
            if detected_topic:
                self.state.active_topic = detected_topic
            if detected_attrs:
                self.state.topic_attributes.update(detected_attrs)
                self.state.current_dialogue_act = DialogueActType.ANSWER

            # 7. User Question Detection
            is_q = (
                raw_text.endswith("?")
                or any(w in raw_text.lower() for w in ["mı", "mi", "mu", "mü", "nasıl", "neden", "ne zaman", "nerede", "hangisi", "kim"])
            )
            if is_q:
                # Save previous question before overwriting
                self.state.last_user_question = raw_text
                self.state.unresolved_question = raw_text
                self.state.current_dialogue_act = DialogueActType.QUESTION

            self._record_turn(
                raw_text, "user", self.state.current_dialogue_act, intent=intent_name,
            )
            return False, None, None

    def record_assistant_turn(
        self,
        text: str,
        explicit_choices: Optional[List[str]] = None,
    ) -> None:
        """Records assistant utterance and extracts questions/choices deterministically."""
        with self._lock:
            if not text or not text.strip():
                return
            raw_text = text.strip()

            self.state.last_assistant_statement = raw_text

            # Check if assistant asked a question
            if raw_text.endswith("?") or any(w in raw_text.lower() for w in ["mı?", "mi?", "mu?", "mü?", "hangisi", "nasıl"]):
                self.state.last_assistant_question = raw_text

            # Determine choice sets (Rule 3)
            if explicit_choices is not None:
                self.state.pending_choices = list(explicit_choices)
            else:
                det_choices = self._extract_deterministic_choices(raw_text)
                if det_choices:
                    self.state.pending_choices = det_choices

            self._record_turn(raw_text, "assistant", DialogueActType.STATEMENT)

    def _record_turn(
        self,
        text: str,
        role: str,
        act: DialogueActType,
        intent: Optional[str] = None,
        resolved: Optional[str] = None,
    ) -> None:
        """Appends a turn to the strictly bounded ring-buffer."""
        turn_rec = TurnRecord(
            turn_id=f"turn_{self.state.turn_count}_{int(time.time()*1000)%10000}",
            speaker_role=role,
            text=text,
            dialogue_act=act,
            intent=intent,
            topic=self.state.active_topic,
            resolved_entity=resolved,
        )
        self.state.recent_turns.append(turn_rec)
