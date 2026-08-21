#!/usr/bin/env python3
"""ASTRO V1 — Single Unified STTRouter.

Manages all Speech-to-Text provider states, cooldowns, quota exhaustion disables,
and seamless fallback to local Faster-Whisper.

Provider States:
  - AVAILABLE: Healthy and ready for requests
  - DEGRADED: Temporary failure, eligible for retry
  - COOLDOWN: 429 RPM rate limited, backoff active
  - EXHAUSTED: Quota/credits exhausted, disabled for session
  - DISABLED: Manually or permanently disabled
"""

import os
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np

from astro_audio.memory_guard import get_system_memory_guard


try:
    from astro_ai.circuit_breaker import (
        GlobalProviderCircuitBreaker,
        ProviderState,
        RequestErrorClass,
        get_global_circuit_breaker,
    )
except ImportError:
    try:
        from circuit_breaker import (
            GlobalProviderCircuitBreaker,
            ProviderState,
            RequestErrorClass,
            get_global_circuit_breaker,
        )
    except ImportError:
        GlobalProviderCircuitBreaker = None
        get_global_circuit_breaker = lambda: None


class STTProviderState(Enum):
    AVAILABLE = "AVAILABLE"
    DEGRADED = "DEGRADED"
    COOLDOWN = "COOLDOWN"
    EXHAUSTED = "EXHAUSTED"
    DISABLED = "DISABLED"


TURKISH_STT_PROMPT = (
    "Astro, robot asistan Astro. Hey Astro, Selam Astro, Astro nasılsın. "
    "Baran, Baran Bey, Ahlat, Bitlis, hava durumu, saat kaç, ne haber, tamam, evet, hayır, dur."
)


@dataclass
class STTRouteResult:
    text: Optional[str] = None
    provider: str = "none"
    state: STTProviderState = STTProviderState.AVAILABLE
    duration_ms: float = 0.0
    fallback_reason: str = "none"
    fallback_chain: List[str] = field(default_factory=list)


class STTRouter:
    """Unified STT Router managing Groq, OpenAI, and Local Faster-Whisper with Global Circuit Breaker."""

    def __init__(
        self,
        groq_client: Optional[Any] = None,
        openai_client: Optional[Any] = None,
        local_whisper_model: Optional[Any] = None,
        logger: Optional[Callable[[str, str], None]] = None,
    ):
        self.groq_client = groq_client
        self.openai_client = openai_client
        self.local_whisper_model = local_whisper_model
        self._log = logger or (lambda lvl, msg: None)
        self.circuit_breaker = get_global_circuit_breaker()

        self.groq_state = STTProviderState.AVAILABLE if groq_client else STTProviderState.DISABLED
        self.groq_cooldown_until = 0.0
        self.groq_consecutive_failures = 0

        self.openai_state = STTProviderState.AVAILABLE if openai_client else STTProviderState.DISABLED
        self.openai_cooldown_until = 0.0
        self.openai_consecutive_failures = 0

        self.local_state = STTProviderState.AVAILABLE if local_whisper_model else STTProviderState.DISABLED

        self.memory_guard = get_system_memory_guard()

    def _safe_log(self, lvl: str, msg: str):
        try:
            if self._log:
                self._log(lvl, msg)
        except Exception:
            pass

    def transcribe(
        self,
        audio_arr: np.ndarray,
        wav_bytes: bytes,
        sample_rate: int = 16000,
    ) -> STTRouteResult:
        """Executes speech transcription through the deterministic state-aware provider hierarchy."""
        now = time.monotonic()
        t_start = time.perf_counter()
        fallback_chain: List[str] = []

        # 1. Attempt Groq Whisper Large V3 (if not in cooldown or disabled)
        groq_cb_available = self.circuit_breaker.is_available("groq", sub_provider="groq_stt") if self.circuit_breaker else True
        if self.groq_client and self.groq_state != STTProviderState.DISABLED and groq_cb_available:
            if self.groq_state == STTProviderState.COOLDOWN and now < self.groq_cooldown_until:
                remaining = self.groq_cooldown_until - now
                fallback_chain.append(f"groq(cooldown_{remaining:.1f}s)")
            else:
                try:
                    res = self.groq_client.audio.transcriptions.create(
                        file=("speech.wav", wav_bytes),
                        model="whisper-large-v3",
                        language="tr",
                        prompt=TURKISH_STT_PROMPT,
                        temperature=0.0,
                        response_format="text",
                    )
                    text = str(res).strip()
                    self.groq_state = STTProviderState.AVAILABLE
                    self.groq_consecutive_failures = 0
                    if self.circuit_breaker:
                        self.circuit_breaker.record_success("groq", sub_provider="groq_stt")
                    fallback_chain.append("groq")
                    return STTRouteResult(
                        text=text,
                        provider="groq/whisper-large-v3",
                        state=self.groq_state,
                        duration_ms=(time.perf_counter() - t_start) * 1000.0,
                        fallback_reason="none",
                        fallback_chain=fallback_chain,
                    )
                except Exception as exc:
                    err_str = str(exc).lower()
                    self.groq_consecutive_failures += 1
                    if "429" in err_str or "rate limit" in err_str or "rpm" in err_str:
                        self.groq_state = STTProviderState.COOLDOWN
                        cooldown_s = 30.0 if self.groq_consecutive_failures <= 1 else 60.0
                        self.groq_cooldown_until = time.monotonic() + cooldown_s
                        if self.circuit_breaker:
                            self.circuit_breaker.record_error("groq", sub_provider="groq_stt", error_class=RequestErrorClass.RATE_LIMITED, error_msg=err_str)
                        self._safe_log("warn", f"⚠️ [STTRouter] Groq 429 RPM Sınırı. {cooldown_s:.0f} saniye COOLDOWN başlatıldı (No retry storm).")
                        fallback_chain.append("groq(429_cooldown)")
                    else:
                        self.groq_state = STTProviderState.DEGRADED
                        if self.circuit_breaker:
                            self.circuit_breaker.record_error("groq", sub_provider="groq_stt", error_class=RequestErrorClass.SERVER_ERROR, error_msg=err_str)
                        fallback_chain.append(f"groq(error:{exc})")
        elif not groq_cb_available:
            st = self.circuit_breaker.get_state("groq", "groq_stt") if self.circuit_breaker else ProviderState.DISABLED
            if st == ProviderState.COOLDOWN:
                fallback_chain.append("groq(cooldown)")
            elif st == ProviderState.EXHAUSTED:
                fallback_chain.append("groq(exhausted)")
            else:
                fallback_chain.append("groq(circuit_breaker_disabled)")

        # 2. Attempt OpenAI Whisper-1 (if not exhausted or disabled)
        openai_cb_available = self.circuit_breaker.is_available("openai", sub_provider="openai_stt") if self.circuit_breaker else True
        if self.openai_client and self.openai_state not in (STTProviderState.DISABLED, STTProviderState.EXHAUSTED) and openai_cb_available:
            if self.openai_state == STTProviderState.COOLDOWN and now < self.openai_cooldown_until:
                remaining = self.openai_cooldown_until - now
                fallback_chain.append(f"openai(cooldown_{remaining:.1f}s)")
            else:
                try:
                    res = self.openai_client.audio.transcriptions.create(
                        model="whisper-1",
                        file=("speech.wav", wav_bytes),
                        language="tr",
                        prompt=TURKISH_STT_PROMPT,
                        temperature=0.0,
                        response_format="text",
                    )
                    text = str(res).strip()
                    self.openai_state = STTProviderState.AVAILABLE
                    self.openai_consecutive_failures = 0
                    if self.circuit_breaker:
                        self.circuit_breaker.record_success("openai", sub_provider="openai_stt")
                    fallback_chain.append("openai")
                    return STTRouteResult(
                        text=text,
                        provider="openai/whisper-1",
                        state=self.openai_state,
                        duration_ms=(time.perf_counter() - t_start) * 1000.0,
                        fallback_reason="groq_unavailable",
                        fallback_chain=fallback_chain,
                    )
                except Exception as exc:
                    err_str = str(exc).lower()
                    self.openai_consecutive_failures += 1
                    if "insufficient_quota" in err_str or "quota" in err_str or "402" in err_str:
                        self.openai_state = STTProviderState.EXHAUSTED
                        if self.circuit_breaker:
                            self.circuit_breaker.record_error("openai", sub_provider="openai_stt", error_class=RequestErrorClass.QUOTA_EXHAUSTED, error_msg=err_str)
                        self._safe_log("error", "🚨 [STTRouter] OpenAI Kota Yetersiz (insufficient_quota). Session boyunca EXHAUSTED yapıldı.")
                        fallback_chain.append("openai(quota_exhausted)")
                    elif "429" in err_str:
                        self.openai_state = STTProviderState.COOLDOWN
                        self.openai_cooldown_until = time.monotonic() + 15.0
                        if self.circuit_breaker:
                            self.circuit_breaker.record_error("openai", sub_provider="openai_stt", error_class=RequestErrorClass.RATE_LIMITED, error_msg=err_str)
                        fallback_chain.append("openai(429_cooldown)")
                    else:
                        self.openai_state = STTProviderState.DEGRADED
                        fallback_chain.append(f"openai(error:{exc})")
        elif not openai_cb_available:
            fallback_chain.append("openai(circuit_breaker_exhausted)")

        # 3. Attempt Local Faster-Whisper
        if self.local_whisper_model:
            try:
                audio_f32 = audio_arr.astype(np.float32) / 32768.0
                segments, _ = self.local_whisper_model.transcribe(
                    audio_f32, beam_size=1, language="tr", initial_prompt=TURKISH_STT_PROMPT
                )
                text = "".join(seg.text for seg in segments).strip()
                fallback_chain.append("local_whisper")
                return STTRouteResult(
                    text=text,
                    provider="local_whisper",
                    state=STTProviderState.AVAILABLE,
                    duration_ms=(time.perf_counter() - t_start) * 1000.0,
                    fallback_reason="cloud_unavailable",
                    fallback_chain=fallback_chain,
                )
            except Exception as exc:
                fallback_chain.append(f"local_whisper(error:{exc})")
                self._safe_log("error", f"❌ [STTRouter] Local Faster-Whisper hatası: {exc}")

        # 4. All STT providers failed
        self._safe_log("error", f"🚨 [STT_ALL_PROVIDERS_FAILED]: All STT transcription providers failed! Chain={fallback_chain}")
        return STTRouteResult(
            text=None,
            provider="none",
            state=STTProviderState.DISABLED,
            duration_ms=(time.perf_counter() - t_start) * 1000.0,
            fallback_reason="STT_ALL_PROVIDERS_FAILED",
            fallback_chain=fallback_chain,
        )
