"""ASTRO V1 — Intent Resolution and Speech Act Classification Engine."""

import re
from typing import Optional, Tuple

from astro_ai.contracts.intent_emotion_types import IntentType


class IntentEngine:
    """Classifies user utterance into structured pragmatic communicative acts."""

    GREETING_PATTERNS = [
        r"\b(?:merhaba|selam|günaydın|gunaydin|iyi günler|iyi aksamlar|iyi akşamlar|hoş geldin|hos geldin)\b",
        r"^(?:hey\s+)?astro[!\.]?$",
    ]
    FAREWELL_PATTERNS = [
        r"\b(?:görüşürüz|gorusuruz|hoşça kal|hosca kal|kendine iyi bak|bay bay|güle güle|iyi geceler)\b"
    ]
    ACTIVITY_QUERY_PATTERNS = [
        r"\b(?:ben\s+)?(?:(?:şu\s*an(?:da)?|şuan)\s+)?ne\s+yap(?:ıyor(?:dur)?|ıyorum|ıyoruz|ıyorsun|maktayım|tığımı)\b",
        r"\b(?:ben\s+)?ne\s+yap(?:ıyor(?:dur)?|ıyorum|ıyoruz|ıyorsun|maktayım|tığımı)(?:\s+(?:şu\s*an(?:da)?|şuan))?\b",
        r"\b(?:benim\s+)?ne\s+yaptığımı\s+(?:gör(?:üyor\s+musun|ebiliyor\s+musun|üyorsun)|bil(?:iyor\s+musun|ebilir\s+misin))\b",
        r"\bbeni\s+görüyorsun,?\s*(?:ben\s+)?ne\s+yap(?:ıyor(?:dur)?|ıyorum|ıyorsun)\b",
        r"\bneyle\s+(?:meşgul(?:üm|sün)|uğraş(?:ıyor(?:dur)?|ıyorum|ıyorsun))\b",
        r"\b(?:şu\s*an(?:da)?\s+)?benim\s+aktivitem\b",
    ]
    VISUAL_STATE_QUERY_PATTERNS = [
        r"\b(?:beni\s+)?(?:kameran(?:dan)?\s+)?gör(?:üyor|ebiliyor)\s+musun(?:\s+beni)?\b",
        r"\b(?:kameran(?:da|dan)?\s+)?neler\s+görüyorsun\b",
        r"\b(?:kameran(?:da|dan)?\s+)?ne\s+görüyorsun\b",
        r"\b(?:kamerada|kameranda)\s+(?:neler\s+var|ne\s+var)\b",
        r"\b(?:karşında\s+|etrafta\s+|etrafımda\s+)?kimi\s+görüyorsun\b",
        r"\b(?:karşında\s+|etrafta\s+|etrafımda\s+)?kim(?:i|ler)\s+var\b",
        r"\b(?:beni\s+)?takip\s+ediyor\s+musun(?:\s+beni)?\b",
        r"\b(?:etrafımda|etrafta|çevrende)\s+ne\s+görüyorsun\b",
    ]
    SOCIAL_BID_PATTERNS = [
        r"\b(?:ne\s+haber|naber|ne\s+var\s+ne\s+yok)\b",
        r"\b(?:neler\s+yapıyorsun|neler\s+dönüyor)\b",
    ]
    QUESTION_PATTERNS = [
        r"(?:\?|kimdir|nedir|nasıl|nasil|kaç|kac|nerede|ne zaman|var mı|mısın|misin|musun|müsün|miyim|miyiz|kim\b)"
    ]
    REQUEST_PATTERNS = [
        r"\b(?:yapar mısın|eder misin|lütfen|bakar mısın|anlatır mısın|söyler misin)\b"
    ]
    MEMORY_UPDATE_PATTERNS = [
        r"\b(?:hatırla|unutma|aklında tut|kaydet|benim adım|tuttuğum takım|favori)\b"
    ]
    MEMORY_QUERY_PATTERNS = [
        r"\b(?:ben kimim|beni tanıyor musun|benim hakkımda ne biliyorsun|adım ne|hatırlıyor musun)\b"
    ]
    CORRECTION_PATTERNS = [
        r"\b(?:hayır|yanlış|öyle değil|öyle demedim|artık\s+.*(?:sevmiyorum|istemiyorum|değil)|değişti|vazgeçtim)\b"
    ]
    EMOTIONAL_PATTERNS = [
        r"\b(?:çok üzgünüm|canım sıkkın|mutsuzum|moralim bozuk|harikayım|çok mutluyum|stresliyim)\b"
    ]
    CONFIRMATION_PATTERNS = [
        r"^(?:evet|tamam|aynen|kesinlikle|olur|peki|tabii|elbette)$"
    ]
    DENIAL_PATTERNS = [
        r"^(?:hayır|yok|asla|olmaz|istemem)$"
    ]

    @classmethod
    def classify_intent(cls, text: str) -> Tuple[IntentType, float]:
        """Classifies speech intent and returns (IntentType, confidence)."""
        if not text or not text.strip():
            return IntentType.UNKNOWN, 0.0

        t = text.lower().strip(" .,!?:;")

        # Normalize/clean leading/trailing wake addressing tokens if other text is present
        # e.g., "astro ben şu anda ne yapıyorum" -> "ben şu anda ne yapıyorum"
        # e.g., "merhaba astro" -> "merhaba"
        cleaned = re.sub(r"^(?:hey\s+)?astro[\s,]+", "", t)
        cleaned = re.sub(r"[\s,]+(?:hey\s+)?astro$", "", cleaned).strip(" .,!?:;")

        target_texts = [cleaned, t] if cleaned and cleaned != t else [t]

        # 1. Exact Confirmations / Denials
        if any(re.search(p, t) for p in cls.CONFIRMATION_PATTERNS):
            return IntentType.CONFIRMATION, 0.98
        if any(re.search(p, t) for p in cls.DENIAL_PATTERNS):
            return IntentType.DENIAL, 0.98

        # 2. Corrections
        if any(re.search(p, txt) for txt in target_texts for p in cls.CORRECTION_PATTERNS):
            return IntentType.CORRECTION, 0.90

        # 3. Activity Queries (high priority to prevent GREETING / STATEMENT fallthrough)
        if any(re.search(p, txt) for txt in target_texts for p in cls.ACTIVITY_QUERY_PATTERNS):
            return IntentType.ACTIVITY_QUERY, 0.95

        # 4. Visual State Queries (high priority: camera/vision state queries)
        if any(re.search(p, txt) for txt in target_texts for p in cls.VISUAL_STATE_QUERY_PATTERNS):
            return IntentType.VISUAL_STATE_QUERY, 0.95

        # 5. Memory Queries
        if any(re.search(p, txt) for txt in target_texts for p in cls.MEMORY_QUERY_PATTERNS):
            return IntentType.MEMORY_QUERY, 0.95

        # 5. Memory Updates
        if any(re.search(p, txt) for txt in target_texts for p in cls.MEMORY_UPDATE_PATTERNS):
            return IntentType.MEMORY_UPDATE, 0.90

        # 6. Social Bids (e.g. "ne haber?", "naber")
        if any(re.search(p, txt) for txt in target_texts for p in cls.SOCIAL_BID_PATTERNS):
            return IntentType.SOCIAL_BID, 0.90

        # 7. Greetings
        if any(re.search(p, txt) for txt in target_texts for p in cls.GREETING_PATTERNS):
            return IntentType.GREETING, 0.95

        # 8. Farewells
        if any(re.search(p, txt) for txt in target_texts for p in cls.FAREWELL_PATTERNS):
            return IntentType.FAREWELL, 0.95

        # 9. Emotional Disclosure
        if any(re.search(p, txt) for txt in target_texts for p in cls.EMOTIONAL_PATTERNS):
            return IntentType.EMOTIONAL_DISCLOSURE, 0.88

        # 10. Requests
        if any(re.search(p, txt) for txt in target_texts for p in cls.REQUEST_PATTERNS):
            return IntentType.REQUEST, 0.85

        # 11. Questions
        if any(re.search(p, txt) for txt in target_texts for p in cls.QUESTION_PATTERNS):
            return IntentType.QUESTION, 0.80

        # 12. General Statements
        return IntentType.STATEMENT, 0.65
