#!/usr/bin/env python3
"""ASTRO V1 — Repetition Guard and Anti-Filler Policy Engine.

Enforces:
  - Anti-canned response policy (blocks standalone fillers like 'Anladım', 'Tamamdır')
  - Session-level recent response memory (FIFO deque maxlen=10)
  - Duplicate utterance detection & template repetition prevention
  - Non-repetitive response diversification
"""

import collections
import re
import unicodedata
from typing import Deque, List, Optional, Set


FORBIDDEN_STANDALONE_FILLERS: Set[str] = {
    "anladim",
    "tamamdir",
    "bakiyorum",
    "bakiyorum hemen",
    "sistemlerimde kaydettim",
    "buradayim",
    "buradayim iste",
    "hallederiz",
    "hallederiz rahat ol",
    "dinliyorum",
    "dinliyorum buyur",
    "devam et",
    "aldim",
    "kaydettim",
}


def normalize_turkish_text(text: str) -> str:
    """Normalizes Turkish text for semantic equality and repetition checking."""
    if not text:
        return ""
    t = text.strip().lower()
    # Turkish char replacements
    t = t.replace("ı", "i").replace("ğ", "g").replace("ü", "u").replace("ş", "s").replace("ö", "o").replace("ç", "c")
    # Strip punctuation and extra spaces
    t = re.sub(r"[^\w\s]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def calculate_jaccard_similarity(str1: str, str2: str) -> float:
    """Calculates token-level Jaccard similarity between two strings."""
    tokens1 = set(normalize_turkish_text(str1).split())
    tokens2 = set(normalize_turkish_text(str2).split())
    if not tokens1 or not tokens2:
        return 0.0
    intersection = tokens1.intersection(tokens2)
    union = tokens1.union(tokens2)
    return len(intersection) / len(union)


class RepetitionGuard:
    """Maintains recent response history and enforces strict non-repetition and anti-filler rules."""

    def __init__(self, history_size: int = 10, similarity_threshold: float = 0.82):
        self.history_size = history_size
        self.similarity_threshold = similarity_threshold
        self._history: Deque[str] = collections.deque(maxlen=history_size)
        self._normalized_history: Deque[str] = collections.deque(maxlen=history_size)

    def is_forbidden_standalone_filler(self, response_text: str) -> bool:
        """Returns True if the response is just a forbidden standalone filler."""
        if not response_text:
            return True
        norm = normalize_turkish_text(response_text)
        if not norm:
            return True

        # Check exact filler matches
        if norm in FORBIDDEN_STANDALONE_FILLERS:
            return True

        # Check if length is tiny and contains only filler words
        words = norm.split()
        if len(words) <= 3 and all(w in ["anladim", "tamamdir", "tamam", "hemen", "bakiyorum", "iste", "buradayim", "kaydettim", "hallederiz", "rahat", "ol", "ulan", "kral", "canim"] for w in words):
            return True

        return False

    def is_repetitive(self, candidate: str) -> bool:
        """Checks if the candidate response was already spoken recently."""
        if not candidate or not self._history:
            return False

        norm_candidate = normalize_turkish_text(candidate)
        if not norm_candidate:
            return False

        for past_norm in self._normalized_history:
            if norm_candidate == past_norm:
                return True
            # For short responses (<= 8 words), high Jaccard similarity indicates template repetition
            sim = calculate_jaccard_similarity(norm_candidate, past_norm)
            if sim >= self.similarity_threshold:
                return True

        return False

    def check_and_record(self, response_text: str) -> tuple[bool, str]:
        """Validates a response against filler and repetition rules.
        
        Returns: (is_valid, reason)
        """
        if not response_text or len(response_text.strip()) < 2:
            return False, "empty_or_too_short"

        if self.is_forbidden_standalone_filler(response_text):
            return False, "forbidden_standalone_filler"

        if self.is_repetitive(response_text):
            return False, "repetitive_response"

        self.record_response(response_text)
        return True, "ok"

    def record_response(self, response_text: str) -> None:
        """Records an approved response into the recent history."""
        if response_text:
            self._history.append(response_text)
            self._normalized_history.append(normalize_turkish_text(response_text))

    def get_recent_responses(self) -> List[str]:
        """Returns the list of recent responses (latest last)."""
        return list(self._history)

    def clear(self) -> None:
        """Clears response history."""
        self._history.clear()
        self._normalized_history.clear()
