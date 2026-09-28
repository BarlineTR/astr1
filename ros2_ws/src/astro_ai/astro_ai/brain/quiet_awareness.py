"""Quiet and Sleep Social Awareness Engine.

Evaluates overhearing background conversations when ASTRO is in quiet or sleep mode:
1. Directed to me? (direct address, wake words, commands, or face-to-face mutual gaze)
2. About me? (third-person references to astro/robot/ai)
3. Does it require robot response or intervention?
4. Output: ENGAGE vs REMAIN_QUIET.
"""

import re
from typing import Any, Optional

from astro_ai.contracts.quiet_awareness_types import (
    DirectednessLevel,
    QuietInterventionNeed,
    QuietDecisionMode,
    QuietAwarenessDecision,
)


class QuietAwarenessEvaluator:
    """Evaluates background speech during quiet/sleep mode to decide whether to engage or remain silent."""

    # Direct address patterns
    DIRECT_PATTERNS = [
        r"\bhey\s+(?:astro|robot)\b",
        r"\bastro\s+(?:uyan|bakar\s+m[ıi]s[ıi]n|dinle|cevap|buraya\s+bak|yard[ıi]m\s+et)\b",
        r"\b(?:uyan|baksana|buraya\s+bak|dinle\s+beni)\s+astro\b",
        r"\buyan\s+robot\b",
        r"\buyan\b",
        r"\bbaksana\b",
        r"\bburaya\s+bak\b",
        r"\bdinle\s+beni\b",
        r"\bbakar\s+m[ıi]s[ıi]n[ıi]z?\b",
    ]

    # Third-person mentions of the robot
    ABOUT_PATTERNS = [
        r"\bastro(?:'ya|ya|'dan|dan|'da|da|'nun|nun|'yu|yu)?\b",
        r"\brobot(?:'a|a|'tan|tan|'ta|ta|'un|un|'u|u)?\b",
        r"\byapay\s+zeka\b",
        r"\basistan\b",
        r"\bmakine\b",
        r"\bcihaz\b",
    ]

    # Explicit question or intervention triggers indicating someone wants info from or about the robot
    INTERVENTION_TRIGGERS = [
        r"soral[ıi]m",
        r"biliyor\s+mu",
        r"uyuyor\s+mu",
        r"duyuyor\s+mu",
        r"duyar\s+m[ıi]",
        r"çalışıyor\s+mu",
        r"açık\s+mı",
        r"yard[ıi]m\s+eder\s+mi",
        r"cevap\s+verir\s+mi",
        r"bizi\s+dinliyor\s+mu",
    ]

    def evaluate_overhearing(
        self,
        user_text: str,
        person: Optional[Any] = None,
        is_quiet_mode: bool = True,
    ) -> QuietAwarenessDecision:
        """Evaluates overheard speech and returns authoritative decision."""
        if not is_quiet_mode:
            return QuietAwarenessDecision(
                mode=QuietDecisionMode.ENGAGE,
                directedness=DirectednessLevel.DIRECTED_TO_ME,
                intervention_need=QuietInterventionNeed.NONE,
                is_about_me=True,
                confidence=1.0,
                reason="NOT_QUIET_MODE",
                prompt_instruction="",
            )

        text_clean = (user_text or "").strip().lower()
        if not text_clean:
            return QuietAwarenessDecision(
                mode=QuietDecisionMode.REMAIN_QUIET,
                directedness=DirectednessLevel.UNRELATED_BACKGROUND,
                intervention_need=QuietInterventionNeed.NONE,
                is_about_me=False,
                confidence=1.0,
                reason="NO_AUDIO_TEXT",
                prompt_instruction=(
                    "SESSİZ/UYKU FARKINDALIK [SESSİZ KAL]: Herhangi bir sesli hitap yok. "
                    "Sessizliğini koru."
                ),
            )

        # Check for face-to-face address
        has_face_to_face = bool(
            person
            and getattr(person, "is_looking_at_robot", False)
            and getattr(person, "distance_m", 2.0) <= 1.5
            and any(g in text_clean for g in ["merhaba", "selam", "günaydın", "iyi günler", "hey", "nasılsın"])
        )

        is_about = any(re.search(pat, text_clean) for pat in self.ABOUT_PATTERNS)
        needs_intervene = any(re.search(pat, text_clean) for pat in self.INTERVENTION_TRIGGERS)

        # 1. Third-party talk about robot requiring intervention ("Bunu Astro'ya soralım mı?")
        if is_about and needs_intervene:
            return QuietAwarenessDecision(
                mode=QuietDecisionMode.ENGAGE,
                directedness=DirectednessLevel.ABOUT_ME,
                intervention_need=QuietInterventionNeed.ASSISTANCE_HELPFUL,
                is_about_me=True,
                confidence=0.88,
                reason="ABOUT_ME_INTERVENTION_NEEDED",
                prompt_instruction=(
                    "SESSİZ/UYKU FARKINDALIK [UYANIŞ / İLGİLİ SORU]: Arka plandaki konuşmada senden bahsedildi ve durumun/bilgin "
                    "hakkında bir soru soruldu. Nazikçe uyanıp araya girerek kendini tanıtabilir veya soruyu yanıtlayabilirsin."
                ),
            )

        # 2. Direct address or face-to-face greeting
        is_direct_regex = any(re.search(pat, text_clean) for pat in self.DIRECT_PATTERNS)
        has_direct_vocative = bool(
            re.search(r"^\s*astro\s*[,!]", text_clean)
            or re.search(r"^\s*astro\s+(?:nasılsın|merhaba|selam|günaydın|yardımına|neredesin)\b", text_clean)
        )
        if is_direct_regex or has_face_to_face or has_direct_vocative:
            return QuietAwarenessDecision(
                mode=QuietDecisionMode.ENGAGE,
                directedness=DirectednessLevel.DIRECTED_TO_ME,
                intervention_need=QuietInterventionNeed.CRITICAL_CALL_OR_COMMAND,
                is_about_me=True,
                confidence=0.95 if is_direct_regex else 0.85,
                reason="DIRECTED_TO_ROBOT",
                prompt_instruction=(
                    "SESSİZ/UYKU FARKINDALIK [UYANIŞ / DOĞRUDAN HİTAP]: Kullanıcı doğrudan sana seslendi veya seni uyandırdı. "
                    "Uyan, sözel yanıt ver ve sohbete doğal şekilde katıl."
                ),
            )

        # 3. Passive mention about robot ("Astro köşede duruyor, çok tatlı.")
        if is_about:
            return QuietAwarenessDecision(
                mode=QuietDecisionMode.REMAIN_QUIET,
                directedness=DirectednessLevel.ABOUT_ME,
                intervention_need=QuietInterventionNeed.NONE,
                is_about_me=True,
                confidence=0.82,
                reason="PASSIVE_MENTION_REMAIN_QUIET",
                prompt_instruction=(
                    "SESSİZ/UYKU FARKINDALIK [SESSİZ GÖZLEM]: Konuşmada senden bahsedildi ancak pasif bir yorum yapıldı; "
                    "senden bir yanıt beklenmiyor. Sessiz kalmaya devam et, sözel araya girme."
                ),
            )

        # 4. Unrelated background speech
        return QuietAwarenessDecision(
            mode=QuietDecisionMode.REMAIN_QUIET,
            directedness=DirectednessLevel.UNRELATED_BACKGROUND,
            intervention_need=QuietInterventionNeed.NONE,
            is_about_me=False,
            confidence=0.90,
            reason="BACKGROUND_CHATTER_REMAIN_QUIET",
            prompt_instruction=(
                "SESSİZ/UYKU FARKINDALIK [SESSİZ KAL]: Arka plandaki konuşma seninle ilgili değil ve sana yönelik değil. "
                "Kesinlikle araya girme, sessizliğini koru."
            ),
        )
