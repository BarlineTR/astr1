#!/usr/bin/env python3
"""ASTRO V1 — Cloud vs Local Fallback Manager.

Coordinates CircuitBreakers for:
  - LLM: Groq Llama-3.3-70b (Primary) <-> Local Llama/Phi-3 or Rule-based Offline (Fallback)
  - STT: Groq Whisper-large-v3 (Primary) <-> Local Whisper/Vosk (Fallback)
  - TTS: Edge-TTS (Primary) <-> Local Piper/espeak or offline beep (Fallback)
"""

import os
import logging
from typing import Optional
from astro_ai.inference_engine import CircuitBreaker, CircuitState

logger = logging.getLogger("astro_cloud_manager")


class CloudManager:
    """Central manager handling cloud availability, timeouts, and local fallback routing."""

    def __init__(self, failure_threshold: int = 3, recovery_timeout_s: float = 30.0):
        self.llm_circuit = CircuitBreaker(failure_threshold, recovery_timeout_s, name="LLM")
        self.stt_circuit = CircuitBreaker(failure_threshold, recovery_timeout_s, name="STT")
        self.tts_circuit = CircuitBreaker(failure_threshold, recovery_timeout_s, name="TTS")

    def is_online(self) -> bool:
        """Returns True if primary cloud services are reachable."""
        return self.llm_circuit.state != CircuitState.OPEN

    def record_llm_success(self):
        self.llm_circuit.record_success()

    def record_llm_failure(self, error: str = ""):
        self.llm_circuit.record_failure(error)

    def should_use_cloud_llm(self) -> bool:
        return self.llm_circuit.should_use_cloud()

    def get_status_summary(self) -> dict:
        return {
            "online": self.is_online(),
            "llm_circuit": self.llm_circuit.state.value,
            "stt_circuit": self.stt_circuit.state.value,
            "tts_circuit": self.tts_circuit.state.value,
        }
