#!/usr/bin/env python3
"""ASTRO V1 — Comprehensive TTS & Speech Latency Telemetry Engine.

Tracks, calculates, and formats end-to-end conversational speech metrics:
  - llm_first_token_ms
  - tts_request_ms
  - tts_first_audio_ms
  - playback_first_audio_ms
  - total_time_to_first_audio_ms (TTFA = playback_first_audio - user_turn_end)
  - synthesis_duration_ms
  - generated_audio_duration_ms
  - real_time_factor (RTF)
  - realtime_to_xtts_failover_ms
  - barge_in_latency_ms
  - gpu_inference_ms
  - gpu_memory_mb
  - cuda_available
  - active_tts_engine
"""

import json
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Optional


@dataclass
class TurnTelemetry:
    """Telemetry data structure for a single conversational turn."""
    turn_id: str = ""
    generation_id: int = 0
    active_tts_engine: str = "unknown"  # "openai_realtime" | "xtts_gpu" | "edge_tts" | "fallback"
    cuda_available: bool = False
    gpu_name: str = ""
    gpu_memory_mb: float = 0.0

    # Timestamp markers (monotonic seconds)
    t_user_turn_end: float = 0.0
    t_llm_request_start: float = 0.0
    t_llm_first_token: float = 0.0
    t_tts_request: float = 0.0
    t_tts_first_audio: float = 0.0
    t_playback_first_audio: float = 0.0
    t_playback_complete: float = 0.0

    # Durations (milliseconds)
    llm_first_token_ms: float = 0.0
    tts_request_ms: float = 0.0
    tts_first_audio_ms: float = 0.0
    playback_first_audio_ms: float = 0.0
    total_time_to_first_audio_ms: float = 0.0  # Main TTFA KPI
    synthesis_duration_ms: float = 0.0
    generated_audio_duration_ms: float = 0.0
    real_time_factor: float = 0.0
    gpu_inference_ms: float = 0.0

    # State & Failover
    realtime_to_xtts_failover_ms: float = 0.0
    barge_in_latency_ms: float = 0.0
    is_interrupted: bool = False
    sentence_count: int = 0
    extra: Dict[str, Any] = field(default_factory=dict)

    def mark_user_turn_end(self, t: Optional[float] = None) -> None:
        self.t_user_turn_end = t or time.monotonic()

    def mark_llm_first_token(self, t: Optional[float] = None) -> None:
        self.t_llm_first_token = t or time.monotonic()
        if self.t_user_turn_end > 0:
            self.llm_first_token_ms = (self.t_llm_first_token - self.t_user_turn_end) * 1000.0

    def mark_tts_request(self, t: Optional[float] = None) -> None:
        self.t_tts_request = t or time.monotonic()
        if self.t_user_turn_end > 0:
            self.tts_request_ms = (self.t_tts_request - self.t_user_turn_end) * 1000.0

    def mark_tts_first_audio(self, t: Optional[float] = None) -> None:
        self.t_tts_first_audio = t or time.monotonic()
        if self.t_user_turn_end > 0:
            self.tts_first_audio_ms = (self.t_tts_first_audio - self.t_user_turn_end) * 1000.0

    def mark_playback_first_audio(self, t: Optional[float] = None) -> None:
        self.t_playback_first_audio = t or time.monotonic()
        if self.t_user_turn_end > 0:
            self.playback_first_audio_ms = (self.t_playback_first_audio - self.t_user_turn_end) * 1000.0
            self.total_time_to_first_audio_ms = self.playback_first_audio_ms

    def record_synthesis(self, synth_ms: float, audio_sec: float, gpu_inf_ms: float = 0.0) -> None:
        self.synthesis_duration_ms += synth_ms
        self.generated_audio_duration_ms += audio_sec * 1000.0
        self.gpu_inference_ms += gpu_inf_ms or synth_ms
        if self.generated_audio_duration_ms > 0:
            self.real_time_factor = round(self.synthesis_duration_ms / self.generated_audio_duration_ms, 3)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)

    def summary_line(self) -> str:
        """Compact single-line diagnostic log."""
        ttfa_str = f"{int(self.total_time_to_first_audio_ms)}ms" if self.total_time_to_first_audio_ms > 0 else "N/A"
        llm_str = f"{int(self.llm_first_token_ms)}ms" if self.llm_first_token_ms > 0 else "N/A"
        tts_str = f"{int(self.tts_first_audio_ms)}ms" if self.tts_first_audio_ms > 0 else "N/A"
        rtf_str = f"{self.real_time_factor:.2f}" if self.real_time_factor > 0 else "N/A"
        gpu_str = f"GPU: {int(self.gpu_inference_ms)}ms ({self.gpu_memory_mb:.0f}MB)" if self.cuda_available else "CPU/Cloud"
        
        status_tag = "🎯 [TTFA < 1.0s SUCCESS]" if (0 < self.total_time_to_first_audio_ms <= 1000.0) else "⚡ [TTFA Telemetry]"
        
        return (
            f"{status_tag} Engine: [{self.active_tts_engine}] | "
            f"TTFA: {ttfa_str} | LLM-TTFT: {llm_str} | TTS-FirstAudio: {tts_str} | "
            f"RTF: {rtf_str} | {gpu_str}"
        )
