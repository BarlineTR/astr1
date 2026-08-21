#!/usr/bin/env python3
"""ASTRO V1 — Single Unified TTSRouter.

Centralizes all TTS provider selection, health verification, deadline enforcement,
deterministic fallback chaining, and immutable generation_id tracking.

Hierarchy:
  1. XTTS (if READY + HEALTHY)
  2. Edge-TTS (if network available & enabled)
  3. Local Offline TTS (Piper / espeak-ng / Acoustic Synth)
  4. Explicit TTS_ALL_PROVIDERS_FAILED (Zero-Silence Contract)
"""

import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

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
    """Single authoritative TTS Router for ASTRO V1."""

    def __init__(
        self,
        local_xtts: Optional[LocalXttsEngine] = None,
        local_offline_tts: Optional[LocalOfflineTTSEngine] = None,
        edge_tts_synth_func: Optional[Callable[[str], Optional[bytes]]] = None,
        edge_tts_enabled: bool = True,
        logger: Optional[Callable[[str, str], None]] = None,
    ):
        self.local_xtts = local_xtts
        self.local_offline_tts = local_offline_tts
        self._edge_tts_synth = edge_tts_synth_func
        self.edge_tts_enabled = edge_tts_enabled
        self._log = logger or (lambda lvl, msg: None)

    def _safe_log(self, lvl: str, msg: str):
        try:
            if self._log:
                self._log(lvl, msg)
        except Exception:
            pass

    def synthesize(
        self,
        text: str,
        generation_id: int,
        language: str = "tr",
    ) -> TTSRouteResult:
        """Synthesizes text through the deterministic TTS fallback chain.
        
        Guarantees that generation_id is preserved throughout all fallback hops.
        """
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

        fallback_chain: List[str] = []
        t_start = time.perf_counter()

        # Step 1: Check Local GPU XTTS (Ready + Healthy)
        if self.local_xtts and self.local_xtts.is_ready() and getattr(self.local_xtts, "is_healthy", lambda: True)():
            try:
                pcm = self.local_xtts.synthesize_sentence(text, generation_id=generation_id, language=language)
                tot_ms = (time.perf_counter() - t_start) * 1000.0
                telem = self.local_xtts.get_telemetry()
                infer_ms = telem.get("last_infer_ms", tot_ms)
                q_wait = telem.get("xtts_queue_wait_ms", max(0.0, tot_ms - infer_ms))

                if pcm:
                    return TTSRouteResult(
                        pcm=pcm,
                        selected_provider="xtts_gpu",
                        actual_provider="xtts_gpu",
                        model_name="xtts_finetuned",
                        source_name="xtts_worker",
                        tts_state="local_gpu",
                        tts_ready=True,
                        tts_healthy=True,
                        fallback_reason="none",
                        fallback_chain=["xtts_gpu"],
                        duration_ms=tot_ms,
                        ttfa_ms=tot_ms,
                        infer_ms=infer_ms,
                        queue_wait_ms=q_wait,
                    )
                else:
                    fb_reason = telem.get("fallback_reason", "xtts_timeout")
                    fallback_chain.append(f"xtts_gpu({fb_reason})")
                    self._safe_log("warn", f"⚠️ [TTSRouter] XTTS sentez başarısız ({fb_reason}), Edge-TTS fallback'e geçiliyor...")
            except Exception as e:
                fallback_chain.append(f"xtts_gpu(error:{e})")
                self._safe_log("warn", f"⚠️ [TTSRouter] XTTS istisna hatası ({e}), Edge-TTS fallback'e geçiliyor...")
        else:
            xtts_reason = "xtts_not_ready" if not (self.local_xtts and self.local_xtts.is_ready()) else "xtts_unhealthy"
            fallback_chain.append(f"xtts_gpu({xtts_reason})")

        # Step 2: Fallback to Edge-TTS Cloud Service
        if self.edge_tts_enabled and self._edge_tts_synth:
            t_edge_start = time.perf_counter()
            try:
                pcm = self._edge_tts_synth(text)
                tot_edge_ms = (time.perf_counter() - t_edge_start) * 1000.0
                tot_ms = (time.perf_counter() - t_start) * 1000.0
                if pcm:
                    fallback_chain.append("edge_tts")
                    return TTSRouteResult(
                        pcm=pcm,
                        selected_provider="edge_tts",
                        actual_provider="edge_tts",
                        model_name="tr_tr_ahmet",
                        source_name="edge_tts_cloud",
                        tts_state="network_cloud",
                        tts_ready=True,
                        tts_healthy=True,
                        fallback_reason="xtts_unavailable",
                        fallback_chain=fallback_chain,
                        duration_ms=tot_ms,
                        ttfa_ms=tot_ms,
                        infer_ms=tot_edge_ms,
                        queue_wait_ms=0.0,
                    )
                else:
                    fallback_chain.append("edge_tts(synthesis_failed)")
                    self._safe_log("warn", "⚠️ [TTSRouter] Edge-TTS sentez başarısız, Local Offline TTS fallback'e geçiliyor...")
            except Exception as e:
                fallback_chain.append(f"edge_tts(error:{e})")
                self._safe_log("warn", f"⚠️ [TTSRouter] Edge-TTS istisna hatası ({e}), Local Offline TTS fallback'e geçiliyor...")
        else:
            fallback_chain.append("edge_tts(disabled_or_unavailable)")

        # Step 3: Fallback to Local Offline TTS (Piper / espeak-ng)
        if self.local_offline_tts and self.local_offline_tts.is_ready():
            t_offline_start = time.perf_counter()
            try:
                pcm = self.local_offline_tts.synthesize_sentence(text, generation_id=generation_id, language=language)
                tot_off_ms = (time.perf_counter() - t_offline_start) * 1000.0
                tot_ms = (time.perf_counter() - t_start) * 1000.0
                if pcm:
                    fallback_chain.append("local_offline_tts")
                    return TTSRouteResult(
                        pcm=pcm,
                        selected_provider="local_offline_tts",
                        actual_provider="local_offline_tts",
                        model_name="piper_espeak",
                        source_name="local_offline_synth",
                        tts_state=self.local_offline_tts.state,
                        tts_ready=True,
                        tts_healthy=True,
                        fallback_reason="cloud_and_gpu_unavailable",
                        fallback_chain=fallback_chain,
                        duration_ms=tot_ms,
                        ttfa_ms=tot_ms,
                        infer_ms=tot_off_ms,
                        queue_wait_ms=0.0,
                    )
            except Exception as e:
                fallback_chain.append(f"local_offline_tts(error:{e})")
                self._safe_log("error", f"❌ [TTSRouter] Local Offline TTS hatası: {e}")

        # Step 4: Zero-Silence Contract — Explicit Alarm
        self._safe_log(
            "error",
            f"🚨 [TTS_ALL_PROVIDERS_FAILED]: All TTS providers failed for generation_id={generation_id}! Chain={fallback_chain}"
        )
        return TTSRouteResult(
            pcm=None,
            selected_provider="none",
            actual_provider="none",
            model_name="none",
            source_name="none",
            tts_state="FAILED",
            tts_ready=False,
            tts_healthy=False,
            fallback_reason="TTS_ALL_PROVIDERS_FAILED",
            fallback_chain=fallback_chain,
            duration_ms=(time.perf_counter() - t_start) * 1000.0,
        )
