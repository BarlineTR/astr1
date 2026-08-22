"""ASTRO V1 — Dedicated Production OpenAI TTS Engine.

Cloud neural TTS over the OpenAI Speech API (`audio.speech.create`).

Neden ayrı bir motor: `realtime_engine.RealtimeEngine` yalnızca bir durum
makinesidir — `synthesize_sentence()` her zaman None döndürür, gerçek ses
`astro_realtime_node` üzerinden WebSocket ile gelir ve o düğüm klasik
`robot.launch.py` boru hattında çalışmaz. Bu motor, Realtime düğümü olmadan da
TTS'in OpenAI üzerinden geçmesini sağlar.

Format notu: `response_format="pcm"` başlıksız 24 kHz, 16-bit signed,
little-endian mono ham PCM döndürür — zincirin (AudioOutputManager) beklediği
formatın aynısı, bu yüzden Edge-TTS'teki gibi bir ffmpeg dönüşümü gerekmez.
"""

import os
import socket
import time
from typing import Any, Callable, Dict, Optional

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None


class OpenAITTSEngine:
    """Production OpenAI cloud TTS engine returning 24kHz int16 mono raw PCM."""

    DEFAULT_MODEL = "gpt-4o-mini-tts"
    DEFAULT_VOICE = "echo"
    DEFAULT_TIMEOUT_S = 6.0

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        voice: Optional[str] = None,
        timeout_s: Optional[float] = None,
        instructions: Optional[str] = None,
        logger: Optional[Callable[[str, str], None]] = None,
    ):
        self._log = logger or (lambda lvl, msg: None)
        self.api_key = (
            api_key
            or os.getenv("OPENAI_API_KEY", "").strip("\"' \t\n\r")
            or os.getenv("AI_API_KEY", "").strip("\"' \t\n\r")
        )
        self.model = model or os.getenv("OPENAI_TTS_MODEL", self.DEFAULT_MODEL)
        self.voice = voice or os.getenv("OPENAI_TTS_VOICE", self.DEFAULT_VOICE)
        self.timeout_s = timeout_s or float(os.getenv("OPENAI_TTS_TIMEOUT_S", str(self.DEFAULT_TIMEOUT_S)))
        # gpt-4o-mini-tts konuşma stilini serbest metinle kabul eder; tts-1 yok sayar.
        self.instructions = instructions if instructions is not None else os.getenv("OPENAI_TTS_INSTRUCTIONS", "")

        self._client = None
        self._last_network_check_ts = 0.0
        self._last_network_ok = True
        self._last_telemetry: Dict[str, Any] = {}

        if OpenAI and self.api_key.startswith("sk-"):
            try:
                self._client = OpenAI(api_key=self.api_key)
            except Exception as exc:
                self._safe_log("error", f"❌ [OpenAI-TTS] client başlatılamadı: {exc}")

        self._safe_log(
            "info",
            f"🤖 [OpenAI-TTS STATE] installed={OpenAI is not None} key={'var' if self.api_key else 'yok'} "
            f"ready={self.is_installed} model={self.model} voice={self.voice}"
        )

    def _safe_log(self, lvl: str, msg: str):
        try:
            if self._log:
                self._log(lvl, msg)
            else:
                print(f"[{lvl.upper()}] {msg}", flush=True)
        except Exception:
            pass

    @property
    def name(self) -> str:
        return "openai_tts"

    @property
    def is_installed(self) -> bool:
        return self._client is not None

    def check_network(self, timeout_s: float = 0.35) -> bool:
        """Fast non-blocking socket probe (Edge-TTS motoruyla aynı 5 sn'lik önbellek)."""
        now = time.monotonic()
        if (now - self._last_network_check_ts) < 5.0:
            return self._last_network_ok

        self._last_network_check_ts = now
        try:
            sock = socket.create_connection(("8.8.8.8", 53), timeout=timeout_s)
            sock.close()
            self._last_network_ok = True
            return True
        except Exception:
            self._last_network_ok = False
            return False

    def is_ready(self) -> bool:
        return self.is_installed and self.check_network(timeout_s=0.25)

    def synthesize_sentence(
        self,
        text: str,
        generation_id: int,
        language: str = "tr",
        voice: Optional[str] = None,
        timeout: Optional[float] = None,
        **kwargs,
    ) -> Optional[bytes]:
        """Synthesizes text via the OpenAI Speech API and returns 24kHz int16 mono raw PCM bytes."""
        if not text or not text.strip():
            return None

        if not self.is_installed:
            self._safe_log(
                "warn",
                f"⚠️ [OpenAI-TTS SYNTHESIS FAILED] generation_id={generation_id} reason=client_unavailable"
            )
            return None

        if not self.check_network(timeout_s=0.3):
            self._safe_log(
                "warn",
                f"⚠️ [OpenAI-TTS SYNTHESIS FAILED] generation_id={generation_id} reason=network_unavailable (fast_skip)"
            )
            return None

        clean_text = text.strip()
        v = voice or self.voice
        t_limit = timeout or self.timeout_s

        self._safe_log(
            "info",
            f"🤖 [OpenAI-TTS SYNTHESIS START] generation_id={generation_id} "
            f"text_length={len(clean_text)} model={self.model} voice={v}"
        )

        t_start = time.perf_counter()
        try:
            params: Dict[str, Any] = {
                "model": self.model,
                "voice": v,
                "input": clean_text,
                "response_format": "pcm",  # 24kHz s16le mono, başlıksız
                "timeout": t_limit,
            }
            if self.instructions:
                params["instructions"] = self.instructions

            response = self._client.audio.speech.create(**params)
            pcm_bytes = response.read()

            tot_ms = (time.perf_counter() - t_start) * 1000.0
            self._last_telemetry = {
                "provider": self.name,
                "model": self.model,
                "voice": v,
                "audio_bytes": len(pcm_bytes) if pcm_bytes else 0,
                "total_ms": round(tot_ms, 1),
            }

            if pcm_bytes and len(pcm_bytes) > 100:
                self._safe_log(
                    "info",
                    f"✅ [OpenAI-TTS SYNTHESIS SUCCESS] generation_id={generation_id} "
                    f"audio_bytes={len(pcm_bytes)} ttfa_ms={tot_ms:.1f} total_ms={tot_ms:.1f}"
                )
                return pcm_bytes

            self._safe_log(
                "warn",
                f"⚠️ [OpenAI-TTS SYNTHESIS FAILED] generation_id={generation_id} reason=empty_audio"
            )
            return None

        except Exception as exc:
            tot_ms = (time.perf_counter() - t_start) * 1000.0
            self._safe_log(
                "warn",
                f"❌ [OpenAI-TTS SYNTHESIS FAILED] generation_id={generation_id} "
                f"reason=exception exception={exc} duration_ms={tot_ms:.1f}"
            )
            return None

    def cancel(self, generation_id: int) -> None:
        """Tek atımlık REST çağrısı; iptal edilecek akış yok."""
        pass

    def get_telemetry(self) -> Dict[str, Any]:
        return dict(self._last_telemetry)
