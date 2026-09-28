#!/usr/bin/env python3
"""ASTRO V1 — Production-Hardened TTS & Speech Latency Telemetry Engine.

Tracks, calculates, and formats end-to-end conversational speech metrics:
  - T0 = user turn end
  - T1 = fallback decision / engine selected
  - T2 = first XTTS inference started
  - T3 = first synthesized audio bytes/chunk available
  - T4 = AudioOutputManager first chunk queued
  - T5 = first playback callback / first audio buffer consumed by DAC
  
Hardware & Software Latency Distinctions:
  - failover_decision_ms (T1 - T0)
  - xtts_first_chunk_ms (T3 - T2)
  - audio_queue_latency_ms (T4 - T3)
  - playback_start_latency_ms (T5 - T4)
  - software_ttfa_ms (T5 - T0: time to first audio buffer consumed in software)
  - estimated_hardware_dac_latency_ms (ALSA/ReSpeaker DMA buffer latency, ~20ms)
  - total_end_to_end_ttfa_ms (software_ttfa_ms + hardware_dac_latency)
"""

import json
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Optional

# Typical ALSA / ReSpeaker UAC1.0 DMA ring buffer period latency (~20ms @ 24kHz/512 frames)
DEFAULT_HARDWARE_DAC_BUFFER_LATENCY_MS = 20.0


@dataclass
class TurnTelemetry:
    """Telemetry data structure for a single conversational turn with explicit software/hardware timing."""
    turn_id: str = ""
    generation_id: int = 0
    active_tts_engine: str = "unknown"  # "openai_realtime" | "xtts_gpu" | "edge_tts" | "fallback"
    failover_state: str = "NORMAL"      # "NORMAL" | "DEGRADED" | "FALLBACK" | "RECOVERING"
    cuda_available: bool = False
    cuda_device: str = "cuda:0"
    gpu_name: str = ""
    gpu_memory_mb: float = 0.0
    gpu_memory_peak_mb: float = 0.0
    system_rss_mb: float = 0.0
    error_class: str = "NONE"

    # Explicit Timestamp Markers (monotonic seconds)
    t0_user_turn_end: float = 0.0
    t1_fallback_selected: float = 0.0
    t2_first_xtts_inference_start: float = 0.0
    t3_first_synthesized_audio: float = 0.0
    t4_audio_manager_submitted: float = 0.0
    t5_playback_dac_consumed: float = 0.0
    t_llm_request_start: float = 0.0
    t_llm_first_token: float = 0.0

    # Software & Hardware Granular Latency Breakdowns (milliseconds)
    failover_decision_ms: float = 0.0
    xtts_first_chunk_ms: float = 0.0
    audio_queue_latency_ms: float = 0.0
    playback_start_latency_ms: float = 0.0
    software_ttfa_ms: float = 0.0
    estimated_hardware_dac_latency_ms: float = DEFAULT_HARDWARE_DAC_BUFFER_LATENCY_MS
    total_end_to_end_ttfa_ms: float = 0.0  # Main TTFA KPI (software_ttfa_ms + dac_latency)

    llm_first_token_ms: float = 0.0
    synthesis_duration_ms: float = 0.0
    generated_audio_duration_ms: float = 0.0
    real_time_factor: float = 0.0
    gpu_inference_ms: float = 0.0

    # Failover & Barge-In
    realtime_to_xtts_failover_ms: float = 0.0
    barge_in_latency_ms: float = 0.0
    is_interrupted: bool = False
    sentence_count: int = 0
    extra: Dict[str, Any] = field(default_factory=dict)

    def mark_user_turn_end(self, t: Optional[float] = None) -> None:
        self.t0_user_turn_end = t or time.monotonic()

    def mark_fallback_selected(self, t: Optional[float] = None) -> None:
        self.t1_fallback_selected = t or time.monotonic()
        if self.t0_user_turn_end > 0:
            self.failover_decision_ms = max(0.0, (self.t1_fallback_selected - self.t0_user_turn_end) * 1000.0)

    def mark_xtts_inference_start(self, t: Optional[float] = None) -> None:
        self.t2_first_xtts_inference_start = t or time.monotonic()

    def mark_synthesized_audio_ready(self, t: Optional[float] = None) -> None:
        self.t3_first_synthesized_audio = t or time.monotonic()
        if self.t2_first_xtts_inference_start > 0:
            self.xtts_first_chunk_ms = max(0.0, (self.t3_first_synthesized_audio - self.t2_first_xtts_inference_start) * 1000.0)

    def mark_audio_manager_submitted(self, t: Optional[float] = None) -> None:
        self.t4_audio_manager_submitted = t or time.monotonic()
        if self.t3_first_synthesized_audio > 0:
            self.audio_queue_latency_ms = max(0.0, (self.t4_audio_manager_submitted - self.t3_first_synthesized_audio) * 1000.0)

    def mark_playback_first_audio(self, t: Optional[float] = None, dac_buffer_latency_ms: Optional[float] = None) -> None:
        self.t5_playback_dac_consumed = t or time.monotonic()
        if dac_buffer_latency_ms is not None:
            self.estimated_hardware_dac_latency_ms = dac_buffer_latency_ms
        if self.t4_audio_manager_submitted > 0:
            self.playback_start_latency_ms = max(0.0, (self.t5_playback_dac_consumed - self.t4_audio_manager_submitted) * 1000.0)
        if self.t0_user_turn_end > 0:
            self.software_ttfa_ms = max(0.0, (self.t5_playback_dac_consumed - self.t0_user_turn_end) * 1000.0)
            self.total_end_to_end_ttfa_ms = self.software_ttfa_ms + self.estimated_hardware_dac_latency_ms

    def mark_llm_first_token(self, t: Optional[float] = None) -> None:
        self.t_llm_first_token = t or time.monotonic()
        if self.t0_user_turn_end > 0:
            self.llm_first_token_ms = max(0.0, (self.t_llm_first_token - self.t0_user_turn_end) * 1000.0)

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
        """Production diagnostic telemetry line."""
        soft_ttfa_str = f"{int(self.software_ttfa_ms)}ms" if self.software_ttfa_ms > 0 else "N/A"
        e2e_ttfa_str = f"{int(self.total_end_to_end_ttfa_ms)}ms" if self.total_end_to_end_ttfa_ms > 0 else "N/A"
        xtts_inf_str = f"{int(self.xtts_first_chunk_ms)}ms" if self.xtts_first_chunk_ms > 0 else "N/A"
        rtf_str = f"{self.real_time_factor:.2f}" if self.real_time_factor > 0 else "N/A"
        gpu_str = f"GPU: {int(self.gpu_inference_ms)}ms ({self.gpu_memory_mb:.0f}MB)" if self.cuda_available else "CPU/Cloud"
        
        status_tag = "🎯 [TTFA < 1.0s SUCCESS]" if (0 < self.total_end_to_end_ttfa_ms <= 1000.0) else "⚡ [TTFA Telemetry]"
        
        return (
            f"{status_tag} Provider: [{self.active_tts_engine}] | "
            f"Software-TTFA: {soft_ttfa_str} | Hardware-TTFA (Est): {e2e_ttfa_str} "
            f"(XTTS-Infer: {xtts_inf_str}, DAC-Buffer: {self.estimated_hardware_dac_latency_ms:.0f}ms) | "
            f"RTF: {rtf_str} | {gpu_str} | Gen: {self.generation_id} | State: {self.failover_state}"
        )
