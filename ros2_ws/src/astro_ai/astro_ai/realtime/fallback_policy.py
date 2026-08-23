"""ASTRO V1 — Realtime başarısızlıklarını sınıflandırma ve kurtarma kararı.

Saf Python: ROS yok, ağ yok, donanım yok. Amaç, "ses gelmedi, ne yapmalı"
sorusunun cevabını canlı bir WebSocket olmadan test edilebilir kılmak.

Canlı logda görülen iki körlüğü kapatır:

1. ``response.done`` olayının ``status`` / ``status_details`` alanları hiç
   okunmuyordu. Yanıtın NEDEN bittiği (completed / failed / cancelled /
   incomplete) ve hata detayı orada. Okunmayınca "ses gelmedi" deyip
   sebebini asla bilemiyorduk.
2. Ses gelmediğinde yalnızca "[TTS FALLBACK] to=edge_tts" LOGLANIYOR, ama
   hiçbir kurtarma çalıştırılmıyordu. Log yalan söylüyordu.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, Optional


class FailureKind(str, Enum):
    NONE = "NONE"
    #: İptal edilmiş yanıt, "cancel not active" gibi zararsız durumlar.
    BENIGN = "BENIGN"
    #: Yanıt kuruldu ama hiç ses üretmedi.
    SILENT_RESPONSE = "SILENT_RESPONSE"
    RATE_LIMIT = "RATE_LIMIT"
    QUOTA = "QUOTA"
    SERVER_ERROR = "SERVER_ERROR"


class RecoveryTier(str, Enum):
    NONE = "NONE"
    #: Model ne diyeceğini yazdı ama sesi gelmedi — metni aynen seslendir.
    SPEAK_ASSISTANT_TEXT = "SPEAK_ASSISTANT_TEXT"
    #: Kullanıcının ne dediğini biliyoruz — yerel olarak cevap üret ve seslendir.
    ANSWER_USER_TEXT = "ANSWER_USER_TEXT"
    #: Henüz ne asistan ne kullanıcı metni var. Deşifre response.done'dan
    #: SONRA gelebiliyor (canlı logda 330 ms sonra geldi) — kısa süre bekle.
    WAIT_FOR_TRANSCRIPT = "WAIT_FOR_TRANSCRIPT"


_RATE_LIMIT_MARKERS = ("rate_limit", "rate limit", "429", "requests per day", "rpd")
_QUOTA_MARKERS = ("insufficient_quota", "credit_balance_exhausted", "quota")
_BENIGN_MARKERS = ("response_cancel_not_active", "cancel")

#: Bunlar kalıcı engellerdir: yeniden bağlanmak aynı duvara toslar.
_PERSISTENT = (FailureKind.RATE_LIMIT, FailureKind.QUOTA)


def _blob(error: Dict[str, Any]) -> str:
    parts = (
        str(error.get("code", "")),
        str(error.get("type", "")),
        str(error.get("message", "")),
    )
    return " ".join(parts).lower()


def classify_error_event(error: Optional[Dict[str, Any]]) -> FailureKind:
    """`error` olayının payload'ını sınıflandırır."""
    if not error:
        return FailureKind.SERVER_ERROR
    text = _blob(error)
    if any(m in text for m in _BENIGN_MARKERS):
        return FailureKind.BENIGN
    if any(m in text for m in _RATE_LIMIT_MARKERS):
        return FailureKind.RATE_LIMIT
    if any(m in text for m in _QUOTA_MARKERS):
        return FailureKind.QUOTA
    return FailureKind.SERVER_ERROR


def classify_response_done(
    response: Optional[Dict[str, Any]], audio_received: bool
) -> FailureKind:
    """`response.done` içindeki ``status`` / ``status_details``'ı sınıflandırır."""
    response = response or {}
    status = str(response.get("status", "")).lower()

    if status == "cancelled":
        # Barge-in ile kesilen yanıt bir hata değildir; kurtarma tetiklenmemeli.
        return FailureKind.BENIGN

    if status == "failed":
        details = response.get("status_details") or {}
        err = details.get("error") or {}
        kind = classify_error_event(err) if err else FailureKind.SERVER_ERROR
        # "failed" durumunda BENIGN anlamsız: yanıt gerçekten başarısız oldu.
        return FailureKind.SERVER_ERROR if kind == FailureKind.BENIGN else kind

    if audio_received:
        return FailureKind.NONE
    return FailureKind.SILENT_RESPONSE


def should_enter_fallback_mode(kind: FailureKind) -> bool:
    """Bu başarısızlık, Realtime'ı tamamen bırakıp yedek hatta geçmeyi gerektirir mi?

    Tek bir sessiz yanıt bağlantıyı terk etmek için sebep değildir; rate limit
    ve quota ise kalıcıdır — yeniden bağlanmak yalnızca aynı duvara toslar.
    """
    return kind in _PERSISTENT


def choose_recovery(
    assistant_text: str,
    user_transcript: str,
    kind: FailureKind = FailureKind.SILENT_RESPONSE,
) -> RecoveryTier:
    """Ses gelmediğinde ne yapılacağına karar verir."""
    if kind in (FailureKind.NONE, FailureKind.BENIGN):
        return RecoveryTier.NONE
    if (assistant_text or "").strip():
        return RecoveryTier.SPEAK_ASSISTANT_TEXT
    if (user_transcript or "").strip():
        return RecoveryTier.ANSWER_USER_TEXT
    return RecoveryTier.WAIT_FOR_TRANSCRIPT
