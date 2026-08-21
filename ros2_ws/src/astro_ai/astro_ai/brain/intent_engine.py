"""ASTRO V1 — Intent Resolution and Speech Act Classification Engine."""

import re
from typing import Optional, Tuple

from astro_ai.contracts.intent_emotion_types import IntentType


class IntentEngine:
    """Classifies user utterance into structured pragmatic communicative acts."""

    GREETING_PATTERNS = [
        r"\b(?:merhaba|selam|günaydın|gunaydin|iyi günler|iyi aksamlar|iyi akşamlar|hey astro|astro)\b"
    ]
    FAREWELL_PATTERNS = [
        r"\b(?:görüşürüz|gorusuruz|hoşça kal|hosca kal|kendine iyi bak|bay bay|güle güle|iyi geceler)\b"
    ]
    QUESTION_PATTERNS = [
        r"(?:\?|kimdir|nedir|nasıl|nasil|kaç|kac|nerede|ne zaman|var mı|mısın|misin|musun|müsün)"
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

        # 1. Exact Confirmations / Denials
        if any(re.search(p, t) for p in cls.CONFIRMATION_PATTERNS):
            return IntentType.CONFIRMATION, 0.98
        if any(re.search(p, t) for p in cls.DENIAL_PATTERNS):
            return IntentType.DENIAL, 0.98

        # 2. Corrections
        if any(re.search(p, t) for p in cls.CORRECTION_PATTERNS):
            return IntentType.CORRECTION, 0.90

        # 3. Memory Queries
        if any(re.search(p, t) for p in cls.MEMORY_QUERY_PATTERNS):
            return IntentType.MEMORY_QUERY, 0.95

        # 4. Memory Updates
        if any(re.search(p, t) for p in cls.MEMORY_UPDATE_PATTERNS):
            return IntentType.MEMORY_UPDATE, 0.90

        # 5. Greetings
        if any(re.search(p, t) for p in cls.GREETING_PATTERNS):
            return IntentType.GREETING, 0.95

        # 6. Farewells
        if any(re.search(p, t) for p in cls.FAREWELL_PATTERNS):
            return IntentType.FAREWELL, 0.95

        # 7. Emotional Disclosure
        if any(re.search(p, t) for p in cls.EMOTIONAL_PATTERNS):
            return IntentType.EMOTIONAL_DISCLOSURE, 0.88

        # 8. Requests
        if any(re.search(p, t) for p in cls.REQUEST_PATTERNS):
            return IntentType.REQUEST, 0.85

        # 9. Questions
        if any(re.search(p, t) for p in cls.QUESTION_PATTERNS):
            return IntentType.QUESTION, 0.80

        # 10. General Statements
        return IntentType.STATEMENT, 0.65
