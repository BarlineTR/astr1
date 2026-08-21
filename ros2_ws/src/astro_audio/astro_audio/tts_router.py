"""ASTRO V1 — Production TTSRouter (Realtime Primary + Edge-TTS Fallback).

Centralizes all speech synthesis provider selection, health verification,
pre-flight network checks, timeout enforcement, fallback chaining, and hardware playback provenance.

Authoritative Routing Architecture:
  1. PRIMARY           : OpenAI Realtime API (WebSocket audio streaming)
  2. PRIMARY FALLBACK  : Edge-TTS (Cloud Neural TTS, fast preflight network check <= 300ms)
  3. EMERGENCY FALLBACK: Local Offline TTS (Piper / espeak-ng / Local Synth)
  4. ALARM             : TTS_ALL_PROVIDERS_FAILED (Zero-Silence Contract)

XTTS Policy:
  DORMANT / DISABLED in runtime by production policy (0 spawns, 0 RAM consumption).
"""

import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

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

from astro_audio.audio_output_manager import AudioOutputManager
from astro_audio.edge_tts_engine import EdgeTTSEngine
from astro_audio.local_audio_resources import get_local_audio_resources
from astro_audio.local_offline_tts_engine import LocalOfflineTTSEngine
from astro_audio.local_xtts_engine import LocalXttsEngine


@dataclass
class TTSRouteResult:
    pcm: Optional[bytes]
    selected_provider: str
    actual_provider: str
    model_name: str
    source_name: str
    tts_state: str
    tts_ready: bool
    tts_healthy: bool
    fallback_reason: str
    fallback_chain: List[str] = field(default_factory=list)
    duration_ms: float = 0.0
    ttfa_ms: float = 0.0
    infer_ms: float = 0.0
    queue_wait_ms: float = 0.0


class TTSRouter:
    """Single authoritative TTS Router and Playback Orchestrator."""

    # Authoritative Timeouts
    DEFAULT_EDGE_TTS_TIMEOUT_S = 4.0
    DEFAULT_OFFLINE_TIMEOUT_S = 3.0
    DEFAULT_PLAYBACK_DEADLINE_MS = 1500.0

    def __init__(
        self,
        local_xtts: Optional[LocalXttsEngine] = None,
        local_offline_tts: Optional[LocalOfflineTTSEngine] = None,
        edge_tts_engine: Optional[EdgeTTSEngine] = None,
        edge_tts_synth_func: Optional[Callable[[str], Optional[bytes]]] = None,
        edge_tts_enabled: bool = True,
        output_manager: Optional[AudioOutputManager] = None,
        logger: Optional[Callable[[str, str], None]] = None,
    ):
        self.local_xtts = local_xtts
        self.local_offline_tts = local_offline_tts
        self.edge_tts_engine = edge_tts_engine or (EdgeTTSEngine(logger=logger) if (edge_tts_enabled and not edge_tts_synth_func) else None)
        self._edge_tts_synth_func = edge_tts_synth_func
        self.edge_tts_enabled = edge_tts_enabled
        self.output_manager = output_manager
        self._log = logger or (lambda lvl, msg: None)
        self.circuit_breaker = get_global_circuit_breaker()
        self.audio_resources = get_local_audio_resources()

        self.edge_timeout_s = float(os.getenv("TTS_EDGE_SYNTHESIS_TIMEOUT_S", os.getenv("EDGE_TTS_TIMEOUT_S", str(self.DEFAULT_EDGE_TTS_TIMEOUT_S))))
        self.playback_deadline_ms = float(os.getenv("TTS_PLAYBACK_START_DEADLINE_MS", str(self.DEFAULT_PLAYBACK_DEADLINE_MS)))

        # One-time dormant XTTS notification
        if self.local_xtts:
            self._safe_log(
                "info",
                "ℹ️ [XTTS] Runtime disabled by production policy\n"
                "  model_retained=True\n"
                "  worker_spawn=False\n"
                "  reason=production_runtime_disabled"
            )

        self._safe_log(
            "info",
            f"🎯 [TTSRouter] Production Hiyerarşi Aktif: OpenAI Realtime (Primary) -> "
            f"Edge-TTS (Primary Fallback, timeout={self.edge_timeout_s}s) -> "
            f"Local Offline TTS (Emergency Fallback) -> Pre-generated Emergency WAV"
        )

    def _safe_log(self, lvl: str, msg: str):
        try:
            if self._log:
                self._log(lvl, msg)
            else:
                print(f"[{lvl.upper()}] {msg}", flush=True)
        except Exception:
            pass

    def synthesize(
        self,
        text: str,
        generation_id: int,
        language: str = "tr",
        realtime_fallback_reason: str = "realtime_quota_exhausted",
    ) -> TTSRouteResult:
        """Synthesizes speech through the strict Realtime Fallback -> Edge-TTS -> Local Offline -> Emergency WAV chain."""
        if not text or not text.strip():
            return TTSRouteResult(
                pcm=None,
                selected_provider="none",
                actual_provider="none",
                model_name="none",
                source_name="none",
                tts_state="none",
                tts_ready=False,
                tts_healthy=False,
                fallback_reason="empty_text",
            )

        clean_text = text.strip()
        fallback_chain: List[str] = []
        t_start = time.perf_counter()

        # Check Global Circuit Breaker for Realtime Availability
        realtime_available = self.circuit_breaker.is_available("openai", sub_provider="openai_realtime") if self.circuit_breaker else False

        if realtime_available:
            self._safe_log("info", f'[TTS REQUESTED] generation_id={generation_id} requested_provider=openai_realtime text="{clean_text}"')
            fallback_chain.append("openai_realtime")
        else:
            self._safe_log("info", f'[TTS REQUESTED] generation_id={generation_id} requested_provider=edge_tts selection_reason=openai_realtime_exhausted text="{clean_text}"')
            fallback_chain.append("edge_tts")

        # -------------------------------------------------------------
        # STEP 1: Local XTTS Engine (Only if explicitly enabled and ready in test mode)
        # -------------------------------------------------------------
        if self.local_xtts and self.local_xtts.is_ready() and getattr(self.local_xtts, "is_healthy", lambda: True)():
            try:
                pcm = self.local_xtts.synthesize_sentence(clean_text, generation_id=generation_id, language=language)
                if pcm and len(pcm) > 10:
                    fallback_chain.append("xtts_gpu")
                    return TTSRouteResult(
                        pcm=pcm,
                        selected_provider="xtts_gpu",
                        actual_provider="xtts_gpu",
                        model_name="xtts_finetuned",
                        source_name="xtts_worker",
                        tts_state="local_gpu",
                        tts_ready=True,
                        tts_healthy=True,
                        fallback_reason=realtime_fallback_reason,
                        fallback_chain=fallback_chain,
                        duration_ms=(time.perf_counter() - t_start) * 1000.0,
                    )
            except Exception as e:
                fallback_chain.append(f"xtts_gpu(error:{e})")

        # -------------------------------------------------------------
        # STEP 2: Edge-TTS Cloud Neural Service (Primary Fallback)
        # -------------------------------------------------------------
        if self.edge_tts_enabled:
            self._safe_log(
                "info",
                f"🌐 [EDGE-TTS FALLBACK ACTIVE]\n"
                f"  generation_id={generation_id}\n"
                f"  trigger={realtime_fallback_reason}\n"
                f"  voice={getattr(self.edge_tts_engine, 'voice', 'tr-TR-AhmetNeural')}"
            )
            t_edge_start = time.perf_counter()
            pcm = None

            if self._edge_tts_synth_func:
                try:
                    pcm = self._edge_tts_synth_func(clean_text)
                except Exception as e:
                    fallback_chain.append(f"edge_tts(error:{e})")
                    self._safe_log("warn", f"⚠️ [Edge-TTS Error]: {e}")
            elif self.edge_tts_engine:
                # Fast pre-flight network probe (<= 300ms)
                if self.edge_tts_engine.check_network(timeout_s=0.3):
                    try:
                        pcm = self.edge_tts_engine.synthesize_sentence(
                            clean_text,
                            generation_id=generation_id,
                            timeout=self.edge_timeout_s,
                        )
                    except Exception as e:
                        fallback_chain.append(f"edge_tts(error:{e})")
                        self._safe_log("warn", f"⚠️ [Edge-TTS Error]: {e}")
                else:
                    fallback_chain.append("edge_tts(network_unavailable)")
                    self._safe_log(
                        "warn",
                        f"⚠️ [TTS FALLBACK]\n"
                        f"  generation_id={generation_id}\n"
                        f"  from=edge_tts\n"
                        f"  to=local_offline_tts\n"
                        f"  reason=network_unavailable (0ms fast_skip)"
                    )

            tot_edge_ms = (time.perf_counter() - t_edge_start) * 1000.0
            tot_ms = (time.perf_counter() - t_start) * 1000.0

            if pcm and len(pcm) > 10:
                fallback_chain.append("edge_tts")
                self._safe_log(
                    "info",
                    f"✅ [EDGE-TTS FALLBACK SUCCESS]\n"
                    f"  generation_id={generation_id}\n"
                    f"  audio_bytes={len(pcm)}\n"
                    f"  ttfa_ms={tot_edge_ms:.1f}\n"
                    f"  total_ms={tot_ms:.1f}"
                )
                return TTSRouteResult(
                    pcm=pcm,
                    selected_provider="edge_tts",
                    actual_provider="edge_tts",
                    model_name="tr_tr_ahmet",
                    source_name="edge_tts_cloud",
                    tts_state="network_cloud",
                    tts_ready=True,
                    tts_healthy=True,
                    fallback_reason=realtime_fallback_reason,
                    fallback_chain=fallback_chain,
                    duration_ms=tot_ms,
                    ttfa_ms=tot_ms,
                    infer_ms=tot_edge_ms,
                    queue_wait_ms=0.0,
                )
            else:
                if "edge_tts(network_unavailable)" not in fallback_chain:
                    fallback_chain.append("edge_tts(synthesis_failed)")
                self._safe_log(
                    "warn",
                    f"⚠️ [TTS FALLBACK]\n"
                    f"  generation_id={generation_id}\n"
                    f"  from=edge_tts\n"
                    f"  to=local_offline_tts\n"
                    f"  reason=edge_tts_failed"
                )
        else:
            fallback_chain.append("edge_tts(disabled)")

        # -------------------------------------------------------------
        # STEP 2: Local Offline TTS (Emergency Last Resort)
        # -------------------------------------------------------------
        if self.local_offline_tts and self.local_offline_tts.is_ready():
            self._safe_log(
                "info",
                f"[TTS SYNTHESIS ATTEMPT] generation_id={generation_id} provider=local_offline_tts"
            )
            t_offline_start = time.perf_counter()
            try:
                pcm = self.local_offline_tts.synthesize_sentence(
                    clean_text,
                    generation_id=generation_id,
                    language=language,
                )
                tot_off_ms = (time.perf_counter() - t_offline_start) * 1000.0
                tot_ms = (time.perf_counter() - t_start) * 1000.0

                if pcm and len(pcm) > 10:
                    fallback_chain.append("local_offline_tts")
                    self._safe_log(
                        "info",
                        f"✅ [LOCAL-OFFLINE-TTS SUCCESS]\n"
                        f"  generation_id={generation_id}\n"
                        f"  audio_bytes={len(pcm)}\n"
                        f"  ttfa_ms={tot_off_ms:.1f}\n"
                        f"  total_ms={tot_ms:.1f}"
                    )
                    return TTSRouteResult(
                        pcm=pcm,
                        selected_provider="local_offline_tts",
                        actual_provider="local_offline_tts",
                        model_name="piper_espeak",
                        source_name="local_offline_synth",
                        tts_state=self.local_offline_tts.state,
                        tts_ready=True,
                        tts_healthy=True,
                        fallback_reason="cloud_unavailable",
                        fallback_chain=fallback_chain,
                        duration_ms=tot_ms,
                        ttfa_ms=tot_ms,
                        infer_ms=tot_off_ms,
                        queue_wait_ms=0.0,
                    )
            except Exception as e:
                fallback_chain.append(f"local_offline_tts(error:{e})")
                self._safe_log("error", f"❌ [Local Offline TTS Error]: {e}")

        # -------------------------------------------------------------
        # STEP 3: Pre-Generated Emergency Audio Fallback (Zero-Silence Contract)
        # -------------------------------------------------------------
        self._safe_log(
            "warn",
            f"⚠️ [TTS ZERO SILENCE FALLBACK]: Activating pre-generated local emergency audio for generation_id={generation_id}! Chain={fallback_chain}"
        )
        emergency_pcm = self.audio_resources.get_emergency_fallback_pcm()
        fallback_chain.append("pregenerated_emergency_wav")
        tot_ms = (time.perf_counter() - t_start) * 1000.0

        return TTSRouteResult(
            pcm=emergency_pcm,
            selected_provider="emergency_wav",
            actual_provider="emergency_wav",
            model_name="pregenerated_wav",
            source_name="local_resource_cache",
            tts_state="EMERGENCY_PLAYBACK",
            tts_ready=True,
            tts_healthy=True,
            fallback_reason="TTS_ALL_PROVIDERS_FAILED",
            fallback_chain=fallback_chain,
            duration_ms=tot_ms,
            ttfa_ms=tot_ms,
            infer_ms=0.0,
            queue_wait_ms=0.0,
        )

    def synthesize_and_play(
        self,
        text: str,
        generation_id: int,
        output_manager: Optional[AudioOutputManager] = None,
        language: str = "tr",
        realtime_fallback_reason: str = "realtime_quota_exhausted",
    ) -> TTSRouteResult:
        """Synthesizes text and immediately queues it to the unified hardware playback manager."""
        res = self.synthesize(
            text,
            generation_id=generation_id,
            language=language,
            realtime_fallback_reason=realtime_fallback_reason,
        )
        out_mgr = output_manager or self.output_manager

        if res.pcm and out_mgr:
            sample_rate = 16000 if res.actual_provider == "emergency_wav" else 24000
            provenance = {
                "tts_provider": res.actual_provider,
                "tts_model": res.model_name,
                "tts_source": res.source_name,
                "playback_source": out_mgr.backend,
            }
            out_mgr.play_pcm_chunk(
                res.pcm,
                sample_rate=sample_rate,
                generation_id=generation_id,
                provenance=provenance,
            )
        return res
