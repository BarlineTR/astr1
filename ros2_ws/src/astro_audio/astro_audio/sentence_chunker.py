#!/usr/bin/env python3
"""ASTRO V1 — Low-Latency Streaming Sentence & Clause Chunker.

Breaks incoming LLM token streams into natural, synthesize-ready clauses
so TTS synthesis can begin on the first clause in < 500ms without waiting
for the full LLM completion.

Features:
  - Smart boundary detection (. ! ? : \n or comma after min characters)
  - Decimal / Number / Abbreviation protection (e.g. 3.14, Dr., vs.)
  - Emoji & Think tag stripping
  - Clean whitespace and Turkish punctuation handling
"""

import re
from typing import List, Optional

EMOJI_RE = re.compile(
    "["
    "\U0001F1E0-\U0001F1FF"
    "\U0001F300-\U0001F5FF"
    "\U0001F600-\U0001F64F"
    "\U0001F680-\U0001F6FF"
    "\U0001F700-\U0001F77F"
    "\U0001F780-\U0001F7FF"
    "\U0001F800-\U0001F8FF"
    "\U0001F900-\U0001F9FF"
    "\U0001FA00-\U0001FAFF"
    "\u2600-\u26FF"
    "\u2700-\u27BF"
    "]+",
    flags=re.UNICODE,
)

ABBREVIATIONS = {"dr.", "prof.", "av.", "vb.", "vd.", "örn.", "vs.", "st.", "mr.", "mrs.", "ms."}


def clean_text_for_tts(text: str) -> str:
    """Removes thinking tags, emojis, markdown, and normalizes spaces."""
    if not text:
        return ""
    text = re.sub(r"(?i)<think>[\s\S]*?</think>", "", text)
    text = re.sub(r"(?i)<\/?think>", "", text)
    text = EMOJI_RE.sub("", text)
    text = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
    text = re.sub(r"`.*?`", "", text)
    text = re.sub(r"[\*\_\~\#\<\>]", "", text)
    text = " ".join(text.split())
    text = re.sub(r"\s+([,.:;?!])", r"\1", text)
    return text.strip()


class SentenceChunker:
    """Incremental clause splitter for streaming LLM generation."""

    def __init__(self, min_first_clause_chars: int = 18, min_clause_chars: int = 28):
        self.min_first_clause_chars = min_first_clause_chars
        self.min_clause_chars = min_clause_chars
        self._buffer = ""
        self._is_first_chunk = True

    def reset(self) -> None:
        self._buffer = ""
        self._is_first_chunk = True

    def feed(self, token: str) -> List[str]:
        """Feed a new token / text chunk, returning any newly completed clauses."""
        if not token:
            return []

        self._buffer += token
        ready_chunks: List[str] = []

        while True:
            split_idx = self._find_split_index(self._buffer)
            if split_idx == -1:
                break

            clause = self._buffer[:split_idx].strip()
            self._buffer = self._buffer[split_idx:].lstrip()

            cleaned = clean_text_for_tts(clause)
            if cleaned and len(cleaned) >= 2:
                ready_chunks.append(cleaned)
                self._is_first_chunk = False

        return ready_chunks

    def flush(self) -> Optional[str]:
        """Flushes any remaining text in the buffer."""
        rem = self._buffer.strip()
        self._buffer = ""
        self._is_first_chunk = True
        cleaned = clean_text_for_tts(rem)
        return cleaned if (cleaned and len(cleaned) >= 2) else None

    def _find_split_index(self, text: str) -> int:
        """Finds the best punctuation split index in text."""
        min_len = self.min_first_clause_chars if self._is_first_chunk else self.min_clause_chars
        if len(text) < min_len:
            return -1

        # Priority 1: Sentence Enders (. ! ? \n)
        for i, char in enumerate(text):
            if char in {".", "!", "?", "\n"}:
                # Check for decimal numbers like 3.14
                if char == "." and i > 0 and i < len(text) - 1 and text[i - 1].isdigit() and text[i + 1].isdigit():
                    continue

                # Check for abbreviations like Dr. or vb.
                prefix_word = text[:i + 1].split()[-1].lower() if text[:i + 1].split() else ""
                if prefix_word in ABBREVIATIONS:
                    continue

                # Valid sentence terminal
                return i + 1

        # Priority 2: Clause Enders (, : ;) after min_len characters with trailing space
        for i in range(min_len, len(text)):
            char = text[i]
            if char in {",", ":", ";"}:
                if i + 1 < len(text) and text[i + 1].isspace():
                    return i + 1

        # Priority 3: Soft split if buffer is excessively long (> 75 chars) on whitespace
        if len(text) > 75:
            last_space = text[:75].rfind(" ")
            if last_space > min_len:
                return last_space + 1

        return -1
