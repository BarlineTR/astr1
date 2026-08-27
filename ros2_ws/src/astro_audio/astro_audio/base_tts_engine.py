#!/usr/bin/env python3
"""ASTRO V1 — Abstract Base Class for Text-to-Speech Engines."""

from abc import ABC, abstractmethod
from typing import Any, Dict, Generator, Optional


class BaseTTSEngine(ABC):
    """Abstract Interface for TTS Engines (OpenAI Realtime, Local XTTS GPU, Edge-TTS)."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Returns the unique name identifier of the engine."""
        pass

    @abstractmethod
    def is_ready(self) -> bool:
        """Returns True if the engine is warm, healthy, and ready for synthesis."""
        pass

    @abstractmethod
    def synthesize_sentence(
        self,
        text: str,
        generation_id: int,
        language: str = "tr",
        **kwargs
    ) -> Optional[bytes]:
        """Synthesizes a single sentence/clause and returns raw int16 PCM bytes or WAV."""
        pass

    @abstractmethod
    def cancel(self, generation_id: int) -> None:
        """Cancels any ongoing generation matching or preceding generation_id."""
        pass

    @abstractmethod
    def get_telemetry(self) -> Dict[str, Any]:
        """Returns engine-specific telemetry (GPU VRAM, CUDA status, RTF, inference times)."""
        pass
