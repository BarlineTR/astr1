"""ASTRO V1 — Dedicated Production Edge-TTS Engine.

Provides high-quality, free cloud neural TTS fallback with fast network probing,
explicit telemetry, timeout enforcement, and 24kHz int16 PCM conversion.
"""

import asyncio
import os
import re
import socket
import subprocess
import time
from typing import Callable, Optional

try:
    import edge_tts
except ImportError:
    edge_tts = None


class EdgeTTSEngine:
    """Production Edge-TTS cloud synthesis engine with fast pre-flight network checks."""

    DEFAULT_VOICE = "tr-TR-AhmetNeural"
    DEFAULT_RATE = "+15%"
    DEFAULT_TIMEOUT_S = 4.0

    def __init__(
        self,
        voice: Optional[str] = None,
        rate: Optional[str] = None,
        timeout_s: Optional[float] = None,
        logger: Optional[Callable[[str, str], None]] = None,
    ):
        self.voice = voice or os.getenv("EDGE_TTS_VOICE", self.DEFAULT_VOICE)
        self.rate = rate or os.getenv("EDGE_TTS_RATE", self.DEFAULT_RATE)
        self.timeout_s = timeout_s or float(os.getenv("EDGE_TTS_TIMEOUT_S", str(self.DEFAULT_TIMEOUT_S)))
        self._log = logger or (lambda lvl, msg: None)
        self._last_network_check_ts = 0.0
        self._last_network_ok = True
        self._check_and_log_initial_state()

    def _safe_log(self, lvl: str, msg: str):
        try:
            if self._log:
                self._log(lvl, msg)
            else:
                print(f"[{lvl.upper()}] {msg}", flush=True)
        except Exception:
            pass

    @property
    def is_installed(self) -> bool:
        return edge_tts is not None

    def check_network(self, timeout_s: float = 0.35) -> bool:
        """Fast non-blocking socket probe to verify outbound internet connectivity (sub-30ms)."""
        now = time.monotonic()
        if (now - self._last_network_check_ts) < 5.0:
            return self._last_network_ok

        self._last_network_check_ts = now
        try:
            # socket.create_connection: idiomatik yol; ayrıca testlerin mock'ladığı
            # API bu (eskiden socket.socket().connect() kullanılıyordu ve
            # test_edge_tts_to_local_offline'ın ağ mock'u hiç devreye girmiyordu).
            sock = socket.create_connection(("8.8.8.8", 53), timeout=timeout_s)
            sock.close()
            self._last_network_ok = True
            return True
        except Exception:
            self._last_network_ok = False
            return False

    def is_ready(self) -> bool:
        return self.is_installed and self.check_network(timeout_s=0.25)

    def _check_and_log_initial_state(self):
        installed = self.is_installed
        net_ok = self.check_network(timeout_s=0.5) if installed else False
        ready = installed and net_ok
        self._safe_log(
            "info",
            f"🌐 [Edge-TTS STATE] installed={installed} network_available={net_ok} ready={ready} voice={self.voice}"
        )

    def synthesize_sentence(
        self,
        text: str,
        generation_id: int,
        voice: Optional[str] = None,
        rate: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> Optional[bytes]:
        """Synthesizes text via Microsoft Edge-TTS and returns 24kHz int16 mono raw PCM bytes."""
        if not text or not text.strip():
            return None

        if not self.is_installed:
            self._safe_log("warn", f"⚠️ [Edge-TTS SYNTHESIS FAILED] generation_id={generation_id} reason=not_installed")
            return None

        if not self.check_network(timeout_s=0.3):
            self._safe_log("warn", f"⚠️ [Edge-TTS SYNTHESIS FAILED] generation_id={generation_id} reason=network_unavailable (fast_skip)")
            return None

        clean_text = text.strip()
        v = voice or self.voice
        r = rate or self.rate
        t_limit = timeout or self.timeout_s

        self._safe_log(
            "info",
            f"🌐 [Edge-TTS SYNTHESIS START] generation_id={generation_id} text_length={len(clean_text)} voice={v}"
        )

        t_start = time.perf_counter()

        # ── 1) MP3 sentezi (asyncio) ─────────────────────────────────────────
        # Event loop try/finally ile kapatılmalı: eskiden loop.close() yalnızca
        # başarı yolundaydı, her timeout/hata bir epoll fd + self-pipe sızdırıyordu
        # ve uzun çalıştırmalar "EMFILE: too many open files" ile bitiyordu.
        loop = asyncio.new_event_loop()

        async def _run_edge_tts():
            communicate = edge_tts.Communicate(clean_text, v, rate=r)
            buf = bytearray()
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    buf.extend(chunk["data"])
            return bytes(buf)

        try:
            mp3_bytes = loop.run_until_complete(
                asyncio.wait_for(_run_edge_tts(), timeout=t_limit)
            )
        except asyncio.TimeoutError:
            tot_ms = (time.perf_counter() - t_start) * 1000.0
            self._safe_log(
                "warn",
                f"⏳ [Edge-TTS SYNTHESIS FAILED] generation_id={generation_id} reason=timeout ({tot_ms:.0f}ms > {t_limit:.1f}s)"
            )
            return None
        except Exception as exc:
            tot_ms = (time.perf_counter() - t_start) * 1000.0
            self._safe_log(
                "warn",
                f"❌ [Edge-TTS SYNTHESIS FAILED] generation_id={generation_id} reason=exception exception={exc} duration_ms={tot_ms:.1f}"
            )
            return None
        finally:
            # communicate.stream() bir async generator; timeout'ta iptal edilir,
            # kapatmadan önce düzgünce sonlandırılmalı.
            try:
                loop.run_until_complete(loop.shutdown_asyncgens())
            except Exception as _exc:
                self._safe_log("debug", f"synthesize_sentence: yok sayılan hata ({_exc})")
            loop.close()

        if not mp3_bytes:
            self._safe_log("warn", f"⚠️ [Edge-TTS SYNTHESIS FAILED] generation_id={generation_id} reason=empty_audio")
            return None

        # ── 2) MP3 -> 24kHz 16-bit mono ham PCM (ffmpeg) ─────────────────────
        try:
            ff_proc = subprocess.Popen(
                ["ffmpeg", "-i", "pipe:0", "-f", "s16le", "-acodec", "pcm_s16le", "-ac", "1", "-ar", "24000", "pipe:1"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
        except Exception as exc:
            self._safe_log(
                "warn",
                f"❌ [Edge-TTS SYNTHESIS FAILED] generation_id={generation_id} reason=ffmpeg_spawn_failed exception={exc}"
            )
            return None

        try:
            pcm_bytes, _ = ff_proc.communicate(input=mp3_bytes, timeout=4.0)
        except subprocess.TimeoutExpired:
            # communicate() zaman aşımında alt süreci ÖLDÜRMEZ; elle temizlenmeli,
            # aksi hâlde her hatada arkada bir ffmpeg süreci kalıyordu.
            ff_proc.kill()
            ff_proc.communicate()
            tot_ms = (time.perf_counter() - t_start) * 1000.0
            self._safe_log(
                "warn",
                f"⏳ [Edge-TTS SYNTHESIS FAILED] generation_id={generation_id} reason=ffmpeg_timeout duration_ms={tot_ms:.1f}"
            )
            return None
        except Exception as exc:
            ff_proc.kill()
            ff_proc.communicate()
            tot_ms = (time.perf_counter() - t_start) * 1000.0
            self._safe_log(
                "warn",
                f"❌ [Edge-TTS SYNTHESIS FAILED] generation_id={generation_id} reason=exception exception={exc} duration_ms={tot_ms:.1f}"
            )
            return None

        tot_ms = (time.perf_counter() - t_start) * 1000.0
        if pcm_bytes and len(pcm_bytes) > 100:
            self._safe_log(
                "info",
                f"✅ [Edge-TTS SYNTHESIS SUCCESS] generation_id={generation_id} audio_bytes={len(pcm_bytes)} ttfa_ms={tot_ms:.1f} total_ms={tot_ms:.1f}"
            )
            return pcm_bytes

        self._safe_log("warn", f"⚠️ [Edge-TTS SYNTHESIS FAILED] generation_id={generation_id} reason=ffmpeg_conversion_failed")
        return None
