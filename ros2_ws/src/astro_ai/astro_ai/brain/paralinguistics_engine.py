#!/usr/bin/env python3
"""ASTRO V1 — Turkish Conversational Paralinguistics & Thinking Fillers Engine.

Provides context-aware Turkish thinking fillers, hesitation markers, and
breath pause formatting without making additional OpenAI API requests (zero extra latency & cost).

Features:
  - Contextual Category Matching (OPINION, VISUAL_SEARCH, EXPLANATION, GUEST_DECORUM, DIRECT_SKIP)
  - Repetition History Guard (FIFO history ring buffer preventing consecutive repetition)
  - Guest Decorum Isolation (Suppresses informal fillers and adopts polite tone when is_known=False)
  - Natural Breath Pause Decorator for Edge-TTS and speech streaming
  - System Prompt Constitution Generator for single-turn zero-cost LLM steering
"""

import collections
import enum
import re
from typing import Deque, List, Optional, Tuple


class ParalinguisticsCategory(str, enum.Enum):
    DIRECT_SKIP = "direct_skip"
    OPINION = "opinion"
    VISUAL_SEARCH = "visual_search"
    EXPLANATION = "explanation"
    GUEST_DECORUM = "guest_decorum"


class ParalinguisticsEngine:
    """Manages natural conversational fillers with zero repetition and zero extra API calls."""

    SKIP_PHRASES = [
        "saat kaç", "hey astro", "iyi akşamlar", "iyi geceler", "ne haber", "günaydın"
    ]

    SKIP_WORDS = {
        "merhaba", "selam", "günaydın", "naber", "dur", "ileri", "geri",
        "sağa", "sola", "dön", "sus", "kapat", "sessiz", "evet",
        "hayır", "tamam", "peki", "oldu", "astro", "git"
    }

    VISUAL_SEARCH_KEYWORDS = {
        "bak", "baksana", "gör", "görüyor musun", "nerede", "neredeyim",
        "bul", "ara", "kim var", "kim geldi", "etrafında", "odada kim var",
        "masada", "neredesin", "gözle", "incele"
    }

    EXPLANATION_KEYWORDS = {
        "nasıl çalışır", "nedir", "açıkla", "neden", "anlat", "nasıl yapılıyor",
        "mantığı ne", "mekanizması", "sebebi ne"
    }

    OPINION_KEYWORDS = {
        "ne düşünüyorsun", "sence", "fikrin ne", "nasıl buldun", "değerlendir",
        "ne dersin", "sence nasıl", "sence mantıklı mı"
    }

    # Contextual candidate pools
    FILLERS_OPINION_INFORMAL = [
        "Hımm... valla şöyle diyeyim abi, ",
        "Açıkçası... ",
        "Bana sorarsan abi... ",
        "Şöyle bir durum var abi, ",
        "Valla şöyle bakıyorum abi, ",
    ]

    FILLERS_VISUAL_INFORMAL = [
        "Dur bi bakayım abi... ",
        "Göz ucuyla bakıyorum... ",
        "Dur bi kontrol edeyim abi... ",
        "Hemen bakıyorum abi... ",
        "Şöyle bir süzüyorum abi... ",
    ]

    FILLERS_EXPLANATION_INFORMAL = [
        "Bak şimdi abi... ",
        "Şöyle ki... ",
        "Mesele şu abi... ",
        "Olayı şöyle izah edeyim abi... ",
    ]

    FILLERS_GUEST_DECORUM = [
        "Efendim şöyle açıklayayım, ",
        "Açıkçası şöyle, ",
        "Şöyle arz edeyim, ",
        "Hemen kontrol ediyorum efendim, ",
        "Bir saniye bakıyorum efendim, ",
    ]

    FILLERS_OPINION_FORMAL = [
        "Hımm... açıkçası şöyle, ",
        "Bana sorarsanız... ",
        "Şöyle bir durum söz konusu, ",
        "Açıkçası... ",
    ]

    def __init__(self, history_size: int = 3):
        self._history_size = history_size
        self._history: Deque[str] = collections.deque(maxlen=history_size)
        self._last_category: Optional[ParalinguisticsCategory] = None
        self._turn_counter: int = 0

    @staticmethod
    def normalize_turkish(text: str) -> str:
        """Turkish-aware case normalization removing unicode combining marks."""
        if not text:
            return ""
        return text.replace("İ", "i").replace("I", "ı").lower().replace("\u0307", "").strip()

    def categorize_query(self, query: str) -> ParalinguisticsCategory:
        """Determines the linguistic category based on semantic intent and tokens."""
        q = self.normalize_turkish(query)
        if not q:
            return ParalinguisticsCategory.DIRECT_SKIP

        # Check skip phrases first
        if any(sp in q for sp in self.SKIP_PHRASES):
            return ParalinguisticsCategory.DIRECT_SKIP

        # Clean punctuation for token matching
        clean_q = re.sub(r"[^\w\s]", " ", q)
        tokens = set(clean_q.split())


        # Check direct skip
        if clean_q in self.SKIP_WORDS or tokens.issubset(self.SKIP_WORDS):
            return ParalinguisticsCategory.DIRECT_SKIP

        # Check visual search intent
        if any(kw in q for kw in self.VISUAL_SEARCH_KEYWORDS):
            return ParalinguisticsCategory.VISUAL_SEARCH

        # Check explanation intent
        if any(kw in q for kw in self.EXPLANATION_KEYWORDS):
            return ParalinguisticsCategory.EXPLANATION

        # Check opinion intent
        if any(kw in q for kw in self.OPINION_KEYWORDS):
            return ParalinguisticsCategory.OPINION

        # Short command/greeting catch
        if len(tokens) <= 2 and any(t in self.SKIP_WORDS for t in tokens):
            return ParalinguisticsCategory.DIRECT_SKIP

        return ParalinguisticsCategory.OPINION


    def select_filler(
        self,
        query: str,
        is_known: bool = True,
        person_name: str = "Baran",
        force_category: Optional[ParalinguisticsCategory] = None,
    ) -> str:
        """Selects a natural conversational Turkish filler with zero consecutive repetition."""
        self._turn_counter += 1
        category = force_category or self.categorize_query(query)
        self._last_category = category

        if category == ParalinguisticsCategory.DIRECT_SKIP:
            return ""

        is_guest = (not is_known) or (str(person_name).strip().lower() in ("misafir", "guest", "unknown", ""))

        if is_guest:
            candidates = self.FILLERS_GUEST_DECORUM
        else:
            if category == ParalinguisticsCategory.VISUAL_SEARCH:
                candidates = self.FILLERS_VISUAL_INFORMAL
            elif category == ParalinguisticsCategory.EXPLANATION:
                candidates = self.FILLERS_EXPLANATION_INFORMAL
            else:
                candidates = self.FILLERS_OPINION_INFORMAL

        # Filter out recently used fillers (Anti-repetition guard)
        available = [f for f in candidates if f not in self._history]
        if not available:
            # If all were used in recent history, choose the one least recently used
            for h in self._history:
                if h in candidates:
                    available = [c for c in candidates if c != self._history[-1]]
                    break
            if not available:
                available = candidates

        # Deterministic rotation based on turn counter & text length to be testable and diverse
        idx = (self._turn_counter + len(query)) % len(available)
        chosen = available[idx]

        self._history.append(chosen)
        return chosen

    def get_recent_history(self) -> List[str]:
        """Returns the recent history of fillers used."""
        return list(self._history)

    def reset_history(self):
        """Clears the history buffer."""
        self._history.clear()
        self._turn_counter = 0

    @staticmethod
    def format_tts_with_pauses(text: str) -> str:
        """Prepares text with natural micro-pauses for Edge-TTS.
        
        Ensures ellipses (...) and hesitation commas are followed by proper
        spacing so that Edge-TTS creates a natural breath pause rather than
        rushing through tokens.
        """
        if not text:
            return ""
        s = text
        # Ensure ellipsis has space after it
        s = re.sub(r"\.{2,}\s*", "... ", s)
        # Normalize double commas or comma after ellipsis
        s = re.sub(r"\.\.\.\s*,", "...", s)
        s = re.sub(r",\s*,+", ", ", s)
        # Ensure single spaces
        s = re.sub(r"\s+", " ", s).strip()
        return s

    @classmethod
    def get_system_prompt_constitution(cls) -> str:
        """Returns the single-turn zero-cost LLM constitution directive."""
        return (
            "DOĞAL TÜRKÇE PARALİNGUİSTİK İFADELER VE DÜŞÜNME DOLGULARI (NATURAL CONVERSATIONAL PARALINGUISTICS):\n"
            "- Robotik bir metin okuyucu gibi anında 0. milisaniyede kusursuz cevap veren yapay bir makine gibi durma; canlı, nefes alan ve düşünen bir insan gibi konuş.\n"
            "- Fikir, yorum ve düşünce gerektiren sorularda söze başlarken doğal düşünme dolguları kullan: 'Hımm... valla şöyle diyeyim...', 'Açıkçası...', 'Şimdi şöyle bir durum var...'.\n"
            "- Arama, nesne bulma, etrafa bakma veya kontrol sorularında: 'Dur bi bakayım abi...', 'Göz ucuyla bakıyorum...', 'Bir saniye inceleyeyim...'.\n"
            "- Mekanizma veya nasıl çalışır açıklama sorularında: 'Bak şimdi abi...', 'Şöyle ki...', 'Mesele şu abi...'.\n"
            "- DÜZ SELAMLAŞMA, TEK KELİMELİK CEVAP VEYA KISA EMİRLERDE ('Selam', 'Saat kaç', 'Dur', 'İleri'): ASLA gereksiz dolgu ekleme! Doğrudan, anında ve net cevap ver.\n"
            "- PAPAĞAN GİBİ ASLA TEKRARLAMA: Her cümlenin başına 'Hımm' veya 'Valla şöyle diyeyim' eklemek KESİNLİKLE YASAKTIR! Dolguları yalnızca konuşmanın doğal aktığı, gerçekten düşünme veya değerlendirme gerektiren anlarda ve her defasında farklı kalıplarla serpiştir."
        )
