#!/usr/bin/env python3
"""ASTRO V1 — Hybrid Production TTS Orchestrator & Circuit Breaker.

Coordinates between Primary (OpenAI Realtime API) and Fallback (Local GPU XTTS v2)
with zero-latency barge-in, low-latency sentence chunking, and comprehensive telemetry.

State Machine:
  - REALTIME_ACTIVE   : Primary OpenAI WebSocket stream active
  - REALTIME_DEGRADED : Connection/quota errors detected; prepping failover
  - XTTS_FALLBACK     : Local GPU XTTS v2 active with pipelined clause synthesis
  - RECOVERING        : Probing Realtime connectivity in background without turn blocking
"""

import enum
import threading
import time
from typing import Any, Callable, Dict, List, Optional

from astro_audio.audio_output_manager import AudioOutputManager
from astro_audio.local_xtts_engine import LocalXttsEngine
from astro_audio.realtime_engine import RealtimeEngine
from astro_audio.sentence_chunker import SentenceChunker
from astro_audio.tts_metrics import TurnTelemetry


class OrchestratorState(enum.Enum):
    REALTIME_ACTIVE = "REALTIME_ACTIVE"
    REALTIME_DEGRADED = "REALTIME_DEGRADED"
    XTTS_FALLBACK = "XTTS_FALLBACK"
    RECOVERING = "RECOVERING"


class TTSOrchestrator:
    """Production hybrid TTS Orchestrator with Circuit Breaker and Pipelined Fallback."""

    def __init__(
        self,
        output_manager: AudioOutputManager,
        realtime_engine: RealtimeEngine,
        local_xtts_engine: Optional[LocalXttsEngine] = None,
        logger=None,
        on_state_change: Optional[Callable[[OrchestratorState], None]] = None,
    ):
        self._log = logger or (lambda lvl, msg: None)
        self.output_manager = output_manager
        self.realtime_engine = realtime_engine
        self.xtts_engine = local_xtts_engine
        self._on_state_change_cb = on_state_change

        self._state = OrchestratorState.REALTIME_ACTIVE
        self._state_lock = threading.Lock()

        # Circuit Breaker Configuration
        self._consecutive_failures = 0
        self._failure_threshold = 2
        self._last_failover_time = 0.0
        self._recovery_probe_interval = 60.0  # seconds
        self._last_probe_time = 0.0

        # Streaming Chunker
        self.chunker = SentenceChunker()

        # Active Turn Telemetry Tracking
        self._current_telemetry: Optional[TurnTelemetry] = None
        self._telemetry_lock = threading.Lock()

        # Register callback with AudioOutputManager to record playback TTFA timestamp
        self.output_manager._on_first_audio = self._on_playback_first_audio

        self._log("info", f"🎯 [TTSOrchestrator] Başlatıldı | Başlangıç Durumu: [{self._state.value}]")

    @property
    def state(self) -> OrchestratorState:
        with self._state_lock:
            return self._state

    def set_state(self, new_state: OrchestratorState) -> None:
        with self._state_lock:
            if self._state != new_state:
                old_state = self._state
                self._state = new_state
                self._log("info", f"🔄 [TTSOrchestrator FSM] Durum Değişti: {old_state.value} -> {new_state.value}")
                if self._on_state_change_cb:
                    self._on_state_change_cb(new_state)

    def start_turn(self, turn_id: str, generation_id: int, user_turn_end_t: Optional[float] = None) -> TurnTelemetry:
        """Initializes telemetry and state for a new user turn."""
        with self._telemetry_lock:
            tel = TurnTelemetry(
                turn_id=turn_id,
                generation_id=generation_id,
                active_tts_engine="openai_realtime" if self._state == OrchestratorState.REALTIME_ACTIVE else "xtts_gpu",
                cuda_available=self.xtts_engine.get_telemetry().get("cuda_available", False) if self.xtts_engine else False,
                gpu_name=self.xtts_engine.get_telemetry().get("gpu_name", "") if self.xtts_engine else "",
                gpu_memory_mb=self.xtts_engine.get_telemetry().get("gpu_memory_mb", 0.0) if self.xtts_engine else 0.0,
            )
            tel.mark_user_turn_end(user_turn_end_t or time.monotonic())
            self._current_telemetry = tel
            self.chunker.reset()
            return tel

    def _on_playback_first_audio(self, generation_id: int, timestamp: float) -> None:
        with self._telemetry_lock:
            if self._current_telemetry and self._current_telemetry.generation_id == generation_id:
                self._current_telemetry.mark_playback_first_audio(timestamp)
                self._log("info", self._current_telemetry.summary_line())

    # ------------------------------------------------------------- Circuit Breaker
    def trip_to_fallback(self, reason: str = "") -> None:
        """Immediately trips the circuit breaker to local XTTS GPU fallback."""
        t_failover_start = time.monotonic()
        with self._state_lock:
            self._consecutive_failures += 1
            self.realtime_engine.set_connected(False)
            self._last_failover_time = t_failover_start
            self._state = OrchestratorState.XTTS_FALLBACK

        failover_ms = (time.monotonic() - t_failover_start) * 1000.0
        with self._telemetry_lock:
            if self._current_telemetry:
                self._current_telemetry.realtime_to_xtts_failover_ms = failover_ms
                self._current_telemetry.active_tts_engine = "xtts_gpu"

        self._log("warn", f"🚨 [TTSOrchestrator Circuit Breaker] Realtime API kesintisi ({reason}). Hızlı Local XTTS GPU Fallback Aktif ({failover_ms:.1f}ms geçiş süresi)!")

    def report_realtime_success(self) -> None:
        """Reports healthy response from OpenAI Realtime API."""
        with self._state_lock:
            self._consecutive_failures = 0
            if self._state != OrchestratorState.REALTIME_ACTIVE:
                self._state = OrchestratorState.REALTIME_ACTIVE
                self.realtime_engine.set_connected(True)
                self._log("info", "✅ [TTSOrchestrator] OpenAI Realtime API sağlıklı ve aktif.")

    def report_realtime_failure(self, err_code: Any, err_msg: str) -> None:
        """Reports failure from Realtime WebSocket."""
        self.realtime_engine.mark_error(err_code, err_msg)
        self.trip_to_fallback(reason=f"{err_code}: {err_msg}")

    # -------------------------------------------------------- Synthesis Pipeline
    def process_token_stream_clause(
        self,
        token: str,
        generation_id: int,
        language: str = "tr",
    ) -> List[bytes]:
        """Pipelined synthesis for incoming LLM tokens. Emits synthesized PCM chunks as clauses complete."""
        if not token:
            return []

        ready_clauses = self.chunker.feed(token)
        pcm_results: List[bytes] = []

        for clause in ready_clauses:
            pcm = self.synthesize_clause(clause, generation_id=generation_id, language=language)
            if pcm:
                pcm_results.append(pcm)

        return pcm_results

    def flush_remaining_stream_clause(
        self,
        generation_id: int,
        language: str = "tr",
    ) -> Optional[bytes]:
        """Flushes any remaining text at LLM completion and synthesizes final clause."""
        tail_clause = self.chunker.flush()
        if tail_clause:
            return self.synthesize_clause(tail_clause, generation_id=generation_id, language=language)
        return None

    def synthesize_clause(
        self,
        text: str,
        generation_id: int,
        language: str = "tr",
        auto_play: bool = True,
    ) -> Optional[bytes]:
        """Synthesizes a single clause using the active local engine and enqueues to speaker."""
        if not text or not self.xtts_engine or not self.xtts_engine.is_ready():
            return None

        t_synth_start = time.perf_counter()
        with self._telemetry_lock:
            if self._current_telemetry and self._current_telemetry.t2_first_xtts_inference_start == 0.0:
                self._current_telemetry.mark_xtts_inference_start()

        pcm = self.xtts_engine.synthesize_sentence(text, generation_id=generation_id, language=language)
        t_synth_end = time.perf_counter()
        synth_ms = (t_synth_end - t_synth_start) * 1000.0

        if pcm:
            # Measure generated audio duration (24kHz or 16kHz)
            sample_rate = getattr(getattr(self.xtts_engine, "client", None), "info", {}).get("sample_rate", 24000) if self.xtts_engine else 24000
            audio_sec = (len(pcm) / 2) / sample_rate

            with self._telemetry_lock:
                if self._current_telemetry:
                    if self._current_telemetry.t3_first_synthesized_audio == 0.0:
                        self._current_telemetry.mark_synthesized_audio_ready()
                    self._current_telemetry.record_synthesis(synth_ms, audio_sec)
                    self._current_telemetry.sentence_count += 1

            if auto_play:
                with self._telemetry_lock:
                    if self._current_telemetry and self._current_telemetry.t4_audio_manager_submitted == 0.0:
                        self._current_telemetry.mark_audio_manager_submitted()
                self.output_manager.play_pcm_chunk(pcm, sample_rate=sample_rate, generation_id=generation_id)

            return pcm

        return None

    def interrupt(self, new_generation_id: Optional[int] = None) -> int:
        """Barge-in interrupt: instantly flushes audio, cancels inference, and resets pipeline."""
        t_barge_start = time.monotonic()
        gen_id = self.output_manager.interrupt(new_generation_id)
        self.chunker.reset()

        if self.xtts_engine:
            self.xtts_engine.cancel(gen_id)

        barge_ms = (time.monotonic() - t_barge_start) * 1000.0
        with self._telemetry_lock:
            if self._current_telemetry:
                self._current_telemetry.is_interrupted = True
                self._current_telemetry.barge_in_latency_ms = barge_ms

        self._log("debug", f"⚡ [TTSOrchestrator] Barge-in tamamlandı ({barge_ms:.2f}ms) -> Gen: {gen_id}")
        return gen_id
