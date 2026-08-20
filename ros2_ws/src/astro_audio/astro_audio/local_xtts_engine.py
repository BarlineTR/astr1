#!/usr/bin/env python3
"""ASTRO V1 — Local Coqui XTTS v2 Engine running on CUDA GPU (cuda:0, FP16).

Implements BaseTTSEngine to provide persistent, sub-second local fallback synthesis
with cached speaker conditioning latents and zero-copy int16 PCM output.
"""

import os
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from astro_audio.base_tts_engine import BaseTTSEngine
from astro_audio.xtts_client import XttsClient, XttsError


def resolve_xtts_home(preferred_home: str = "") -> str:
    """Finds existing XTTS home directory containing virtualenv and Coqui TTS."""
    candidates = [
        preferred_home,
        os.getenv("TTS_XTTS_HOME", ""),
        os.path.expanduser("~/.astro/tts"),
        "/home/okistech/.astro/tts",
        os.path.expanduser("~/Desktop/astr1/tts"),
        os.path.abspath("./tts"),
    ]
    for cand in candidates:
        if cand and os.path.exists(cand):
            venv_py = os.path.join(cand, ".venv", "bin", "python")
            venv_py_win = os.path.join(cand, ".venv", "Scripts", "python.exe")
            if os.path.exists(venv_py) or os.path.exists(venv_py_win):
                return os.path.abspath(cand)

    # Return standard default location
    return os.path.expanduser("~/.astro/tts")


def resolve_xtts_speaker_wav(preferred_wav: str = "") -> str:
    """Resolves and validates reference speaker WAV audio file with priority for fine-tuned reference.wav."""
    candidates: List[str] = [
        preferred_wav,
        os.getenv("TTS_XTTS_SPEAKER_WAV", ""),
    ]

    # Model directory / checkpoint directory reference WAV
    ckpt = os.getenv("TTS_XTTS_CHECKPOINT", "")
    mdir = os.getenv("TTS_XTTS_MODEL_DIR", "")
    for base_p in [mdir, str(Path(os.path.expanduser(ckpt)).parent) if ckpt else ""]:
        if base_p and os.path.exists(base_p):
            candidates.extend([
                os.path.join(base_p, "reference.wav"),
                os.path.join(base_p, "speaker.wav"),
                os.path.join(base_p, "Recording.wav"),
            ])

    # Standard fine-tune directory locations
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
    candidates.extend([
        "/home/okistech/Desktop/astr1/models/xtts_finetune_ready_v2/reference.wav",
        os.path.join(root_dir, "models", "xtts_finetune_ready_v2", "reference.wav"),
        os.path.expanduser("~/.astro/models/xtts_finetune_ready_v2/reference.wav"),
        os.path.abspath("./models/xtts_finetune_ready_v2/reference.wav"),
    ])

    try:
        from ament_index_python.packages import get_package_share_directory
        share_wav = os.path.join(get_package_share_directory("astro_audio"), "voices", "astro.wav")
        candidates.append(share_wav)
    except Exception:
        pass

    # Source and install directory candidates
    candidates.extend([
        os.path.join(root_dir, "ros2_ws", "src", "astro_audio", "voices", "astro.wav"),
        os.path.join(root_dir, "ros2_ws", "install", "astro_audio", "share", "astro_audio", "voices", "astro.wav"),
        os.path.expanduser("~/.astro/tts/Recording.wav"),
        os.path.expanduser("~/.astro/tts/voices/astro.wav"),
        os.path.expanduser("~/.astro/voices/astro.wav"),
        "/home/okistech/Desktop/astr1/ros2_ws/install/astro_audio/share/astro_audio/voices/astro.wav",
        "/home/okistech/Desktop/astr1/ros2_ws/src/astro_audio/voices/astro.wav",
    ])

    for cand in candidates:
        if cand and os.path.exists(cand) and os.path.getsize(cand) > 500:
            return os.path.abspath(cand)

    # Fallback to default expected path
    return os.path.expanduser("~/.astro/tts/Recording.wav")


class LocalXttsEngine(BaseTTSEngine):
    """Local Coqui XTTS v2 Engine running resident on CUDA GPU."""

    def __init__(
        self,
        speaker_wav: str = "",
        language: str = "tr",
        device: str = "cuda",
        half: bool = True,
        home: Optional[str] = None,
        model_dir: Optional[str] = None,
        checkpoint: Optional[str] = None,
        config: Optional[str] = None,
        vocab: Optional[str] = None,
        speakers: Optional[str] = None,
        logger: Optional[Callable[[str, str], None]] = None,
    ):
        self._log = logger or (lambda lvl, msg: None)
        self.home = resolve_xtts_home(home or "")
        self.speaker_wav = resolve_xtts_speaker_wav(speaker_wav or "")
        self.language = language
        self.device = device
        self.half = half

        ckpt = checkpoint or os.getenv("TTS_XTTS_CHECKPOINT") or None
        cfg = config or os.getenv("TTS_XTTS_CONFIG") or None
        voc = vocab or os.getenv("TTS_XTTS_VOCAB") or None
        spks = speakers or os.getenv("TTS_XTTS_SPEAKERS") or None
        md = model_dir or os.getenv("TTS_XTTS_MODEL_DIR") or None

        self.client = XttsClient(
            speaker_wav=self.speaker_wav,
            home=self.home,
            language=language,
            device=device,
            half=half,
            model_dir=md,
            checkpoint=ckpt,
            config=cfg,
            vocab=voc,
            speakers=spks,
            logger=self._safe_log,
        )

        self._state = "STOPPED"  # STOPPED, STARTING, READY, DEGRADED, CRASHED, STOPPING
        self._state_lock = threading.Lock()

        self._last_telemetry: Dict[str, Any] = {
            "device": device,
            "cuda_available": False,
            "gpu_name": "",
            "gpu_memory_mb": 0.0,
            "rtf": 0.0,
            "last_infer_ms": 0.0,
            "worker_pid": None,
            "ready": False,
            "state": "STOPPED",
            "is_finetuned": bool(self.client.custom_model and self.client.custom_model.get("checkpoint")),
        }

    def _safe_log(self, lvl: str, msg: str) -> None:
        """Safely dispatches log message without letting ROS2 severity context errors bubble up."""
        try:
            if self._log:
                self._log(lvl, msg)
        except Exception:
            try:
                print(f"[{lvl.upper()}] {msg}", flush=True)
            except Exception:
                pass

    @property
    def name(self) -> str:
        return "xtts_gpu"

    @property
    def state(self) -> str:
        with self._state_lock:
            return self._state

    def start(self) -> None:
        """Starts the persistent XTTS worker and verifies GPU warm-up. Guarantees single worker process."""
        with self._state_lock:
            if self._state == "READY" and self.client.is_alive and self.client.is_ready:
                self._safe_log("debug", f"LocalXttsEngine is already READY (PID: {getattr(self.client.proc, 'pid', None)}).")
                return
            if self._state == "STARTING" and self.client.is_alive:
                self._safe_log("debug", f"LocalXttsEngine is already in STARTING state (PID: {getattr(self.client.proc, 'pid', None)}). Reusing worker.")
                return
            self._state = "STARTING"

        self._safe_log("info", f"🚀 [LocalXttsEngine] GPU XTTS başlatılıyor... (Referans: {self.speaker_wav}, Home: {self.home}, Cihaz: {self.device})")
        
        if not os.path.exists(self.home):
            with self._state_lock:
                self._state = "STOPPED"
            raise XttsError(f"XTTS dizini yok: {self.home} — Lütfen './scripts/install_xtts.sh' betiğini çalıştırın.")

        if not os.path.exists(self.speaker_wav):
            self._safe_log("warn", f"⚠️ [LocalXttsEngine] Referans ses dosyası bulunamadı ({self.speaker_wav}), standart sentez denenecek.")

        self.client.start()
        try:
            info = self.client.wait_ready(timeout=180.0)
            worker_pid = self.client.proc.pid if self.client.proc else None
            with self._state_lock:
                self._state = "READY"
            self._last_telemetry.update({
                "gpu_name": info.get("gpu", "cuda:0"),
                "gpu_memory_mb": info.get("gpu_memory_mb", 0.0),
                "cuda_available": info.get("device") == "cuda",
                "worker_pid": worker_pid,
                "ready": True,
                "state": "READY",
            })
            self._safe_log(
                "info",
                f"✅ [LocalXttsEngine] XTTS GPU Resident Hazır! ({info.get('gpu')}, PID: {worker_pid}, "
                f"VRAM: {info.get('gpu_memory_mb')}MB, FP16: {info.get('half')})"
            )
        except XttsError as e:
            with self._state_lock:
                self._state = "CRASHED"
            self._last_telemetry["ready"] = False
            self._last_telemetry["state"] = "CRASHED"
            self._safe_log("error", f"❌ [LocalXttsEngine] XTTS başlatılamadı: {e}")
            raise

    def is_ready(self) -> bool:
        with self._state_lock:
            return self._state == "READY" and self.client.is_ready

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
                "ready": True,
                "state": "READY",
            })

            return pcm_bytes

        except Exception as exc:
            self._safe_log("warn", f"⚠️ [LocalXttsEngine] Sentez hatası: {exc}")
            if not self.client.is_alive:
                with self._state_lock:
                    self._state = "CRASHED"
                self._last_telemetry["ready"] = False
                self._last_telemetry["state"] = "CRASHED"
                self._safe_log("error", "❌ [LocalXttsEngine] XTTS worker süreci çökmüş! Arka planda yeniden başlatılıyor...")
                threading.Thread(target=self._try_auto_restart, daemon=True).start()
            return None

    def _try_auto_restart(self) -> None:
        try:
            with self._state_lock:
                self._state = "STOPPING"
            self.client.stop()
            time.sleep(0.5)
            self.start()
        except Exception as e:
            with self._state_lock:
                self._state = "CRASHED"
            self._safe_log("error", f"❌ [LocalXttsEngine] Yeniden başlatma başarısız: {e}")

    def cancel(self, generation_id: int) -> None:
        self.client.interrupt(generation_id)

    def get_telemetry(self) -> Dict[str, Any]:
        info = dict(self._last_telemetry)
        if self.client.info:
            info.update(self.client.info)
        if self.client.proc:
            info["worker_pid"] = self.client.proc.pid
        info["ready"] = self.is_ready()
        info["xtts_reference_wav"] = self.client.info.get("xtts_reference_wav", self.speaker_wav)
        info["xtts_model_path"] = self.client.info.get("xtts_model_path", self.client.model)
        info["xtts_checkpoint_sha256"] = self.client.info.get("xtts_checkpoint_sha256", "none")
        info["is_finetuned"] = bool(self.client.custom_model and self.client.custom_model.get("checkpoint"))
        with self._state_lock:
            info["state"] = self._state
        return info

    def stop(self) -> None:
        with self._state_lock:
            self._state = "STOPPING"
        self.client.stop()
        with self._state_lock:
            self._state = "STOPPED"
        self._last_telemetry["ready"] = False
        self._last_telemetry["state"] = "STOPPED"
