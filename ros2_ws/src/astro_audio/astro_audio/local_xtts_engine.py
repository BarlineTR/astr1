#!/usr/bin/env python3
"""ASTRO V1 — Local Coqui XTTS v2 Engine running on CUDA GPU (cuda:0, FP16).

Implements BaseTTSEngine to provide persistent, sub-second local fallback synthesis
with cached speaker conditioning latents and zero-copy int16 PCM output.
"""

import os
import time
from typing import Any, Dict, Optional

from astro_audio.base_tts_engine import BaseTTSEngine
from astro_audio.xtts_client import XttsClient, XttsError


class LocalXttsEngine(BaseTTSEngine):
    """Local Coqui XTTS v2 Engine running resident on CUDA GPU."""

    def __init__(
        self,
        speaker_wav: str,
        language: str = "tr",
        device: str = "cuda",
        half: bool = True,
        home: Optional[str] = None,
        model_dir: Optional[str] = None,
        logger=None,
    ):
        self._log = logger or (lambda lvl, msg: None)
        self.speaker_wav = speaker_wav
        self.language = language
        self.device = device
        self.half = half

        self.client = XttsClient(
            speaker_wav=speaker_wav,
            home=home,
            language=language,
            device=device,
            half=half,
            model_dir=model_dir,
            logger=logger,
        )

        self._last_telemetry: Dict[str, Any] = {
            "device": device,
            "cuda_available": device == "cuda",
            "gpu_name": "",
            "gpu_memory_mb": 0.0,
            "rtf": 0.0,
            "last_infer_ms": 0.0,
        }

    @property
    def name(self) -> str:
        return "xtts_gpu"

    def start(self) -> None:
        """Starts the persistent XTTS worker and verifies GPU warm-up."""
        self._log("info", f"🚀 [LocalXttsEngine] GPU XTTS başlatılıyor... (Referans: {self.speaker_wav}, Cihaz: {self.device})")
        self.client.start()
        try:
            info = self.client.wait_ready(timeout=180.0)
            self._last_telemetry.update({
                "gpu_name": info.get("gpu", "cuda:0"),
                "gpu_memory_mb": info.get("gpu_memory_mb", 0.0),
                "cuda_available": info.get("device") == "cuda",
            })
            self._log("info", f"✅ [LocalXttsEngine] XTTS GPU Resident Hazır! ({info.get('gpu')}, VRAM: {info.get('gpu_memory_mb')}MB, FP16: {info.get('half')})")
        except XttsError as e:
            self._log("error", f"❌ [LocalXttsEngine] XTTS başlatılamadı: {e}")
            raise

    def is_ready(self) -> bool:
        return self.client.is_ready

    def synthesize_sentence(
        self,
        text: str,
        generation_id: int,
        language: str = "tr",
        **kwargs
    ) -> Optional[bytes]:
        """Synthesizes text clause and returns raw int16 PCM bytes."""
        if not self.is_ready():
            return None

        t_start = time.perf_counter()
        try:
            res = self.client.synthesize_chunk(
                text=text,
                generation_id=generation_id,
                return_pcm=True,
                language=language or self.language,
                timeout=20.0,
            )

            if res.get("cancelled") or not res.get("ok"):
                return None

            pcm_bytes = res.get("pcm_bytes")
            gpu_ms = res.get("gpu_inference_ms", 0.0)
            rtf = res.get("rtf", 0.0)
            vram = res.get("gpu_memory_mb", 0.0)

            self._last_telemetry.update({
                "last_infer_ms": gpu_ms,
                "rtf": rtf,
                "gpu_memory_mb": vram,
            })

            return pcm_bytes

        except Exception as exc:
            self._log("warn", f"⚠️ [LocalXttsEngine] Sentez hatası: {exc}")
            return None

    def cancel(self, generation_id: int) -> None:
        self.client.interrupt(generation_id)

    def get_telemetry(self) -> Dict[str, Any]:
        return dict(self._last_telemetry)

    def stop(self) -> None:
        self.client.stop()
