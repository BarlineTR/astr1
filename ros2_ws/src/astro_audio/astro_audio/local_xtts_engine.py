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


def resolve_fine_tune_paths(
    checkpoint: Optional[str] = None,
    config: Optional[str] = None,
    vocab: Optional[str] = None,
    speakers: Optional[str] = None,
    speaker_wav: Optional[str] = None,
    model_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """Resolves and validates all required paths for the fine-tuned XTTS model."""
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
    base_dirs = [
        model_dir,
        os.getenv("TTS_XTTS_MODEL_DIR"),
        "/home/okistech/Desktop/astr1/models/xtts_finetune_ready_v2",
        os.path.join(root_dir, "models", "xtts_finetune_ready_v2"),
        os.path.abspath("./models/xtts_finetune_ready_v2"),
        os.path.expanduser("~/.astro/models/xtts_finetune_ready_v2"),
    ]
    resolved_dir = None
    for bd in base_dirs:
        if bd and os.path.exists(bd) and os.path.exists(os.path.join(bd, "model.pth")):
            resolved_dir = os.path.abspath(bd)
            break

    ckpt_path = checkpoint or os.getenv("TTS_XTTS_CHECKPOINT") or (os.path.join(resolved_dir, "model.pth") if resolved_dir else None)
    cfg_path = config or os.getenv("TTS_XTTS_CONFIG") or (os.path.join(resolved_dir, "config.json") if resolved_dir else None)
    voc_path = vocab or os.getenv("TTS_XTTS_VOCAB") or (os.path.join(resolved_dir, "vocab.json") if resolved_dir else None)
    spk_path = speakers or os.getenv("TTS_XTTS_SPEAKERS") or (os.path.join(resolved_dir, "speakers_xtts.pth") if resolved_dir else None)
    ref_path = speaker_wav or os.getenv("TTS_XTTS_SPEAKER_WAV") or (os.path.join(resolved_dir, "reference.wav") if resolved_dir else None)

    ckpt_exists = bool(ckpt_path and os.path.exists(ckpt_path))
    cfg_exists = bool(cfg_path and os.path.exists(cfg_path))
    voc_exists = bool(voc_path and os.path.exists(voc_path))
    spk_exists = bool(spk_path and os.path.exists(spk_path))
    ref_exists = bool(ref_path and os.path.exists(ref_path))

    return {
        "model_dir": resolved_dir,
        "checkpoint": os.path.abspath(ckpt_path) if ckpt_path else None,
        "config": os.path.abspath(cfg_path) if cfg_path else None,
        "vocab": os.path.abspath(voc_path) if voc_path else None,
        "speakers": os.path.abspath(spk_path) if spk_path else None,
        "speaker_wav": os.path.abspath(ref_path) if ref_path else None,
        "checkpoint_exists": ckpt_exists,
        "config_exists": cfg_exists,
        "vocab_exists": voc_exists,
        "speakers_exists": spk_exists,
        "reference_exists": ref_exists,
        "all_required_exist": bool(ckpt_exists and cfg_exists and voc_exists and ref_exists),
    }


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
        self.language = language
        self.device = device
        self.half = half

        # Resolve and proof all fine-tuned checkpoint files
        self.ft_paths = resolve_fine_tune_paths(
            checkpoint=checkpoint,
            config=config,
            vocab=vocab,
            speakers=speakers,
            speaker_wav=speaker_wav,
            model_dir=model_dir,
        )
        self.speaker_wav = self.ft_paths["speaker_wav"] or resolve_xtts_speaker_wav(speaker_wav or "")

        # Log Environment Proof immediately on startup
        self._safe_log(
            "info",
            f"🔍 [XTTS Environment Proof]:\n"
            f"  TTS_XTTS_CHECKPOINT={self.ft_paths['checkpoint']} (exists={self.ft_paths['checkpoint_exists']})\n"
            f"  TTS_XTTS_CONFIG={self.ft_paths['config']} (exists={self.ft_paths['config_exists']})\n"
            f"  TTS_XTTS_VOCAB={self.ft_paths['vocab']} (exists={self.ft_paths['vocab_exists']})\n"
            f"  TTS_XTTS_SPEAKERS={self.ft_paths['speakers']} (exists={self.ft_paths['speakers_exists']})\n"
            f"  TTS_XTTS_SPEAKER_WAV={self.ft_paths['speaker_wav']} (exists={self.ft_paths['reference_exists']})"
        )

        self.client = XttsClient(
            speaker_wav=self.speaker_wav,
            home=self.home,
            language=language,
            device=device,
            half=half,
            model_dir=self.ft_paths["model_dir"],
            checkpoint=self.ft_paths["checkpoint"],
            config=self.ft_paths["config"],
            vocab=self.ft_paths["vocab"],
            speakers=self.ft_paths["speakers"],
            logger=self._safe_log,
        )

        self._state = "STOPPED"  # STOPPED, STARTING, READY, CRASHED, COOLDOWN, STOPPING
        self._state_lock = threading.Lock()
        self._cooldown_duration = float(os.getenv("XTTS_COOLDOWN_S", "60.0"))
        self._cooldown_until = 0.0

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
            "is_finetuned": bool(self.ft_paths["checkpoint_exists"]),
            "xtts_model_path": self.ft_paths["checkpoint"] or "none",
            "xtts_checkpoint_sha256": "none",
            "error": "none" if self.ft_paths["all_required_exist"] else "missing_fine_tuned_files",
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
            if self._state == "COOLDOWN" and time.monotonic() >= self._cooldown_until:
                self._state = "STOPPED"
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
            now_m = time.monotonic()
            if self._state == "COOLDOWN" and now_m < self._cooldown_until:
                rem_s = self._cooldown_until - now_m
                self._safe_log("warn", f"⏳ [LocalXttsEngine] XTTS is in COOLDOWN ({rem_s:.1f}s remaining). Spawn refused.")
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
                "xtts_model_path": info.get("xtts_model_path", self.speaker_wav),
                "xtts_checkpoint_sha256": info.get("xtts_checkpoint_sha256", "none"),
                "is_finetuned": info.get("is_finetuned", False),
                "error": "none",
            })
            model_type_str = "xtts_finetuned" if info.get("is_finetuned") else "xtts_v2"
            self._safe_log(
                "info",
                f"✅ [XTTS READY]\n"
                f"  model={model_type_str}\n"
                f"  checkpoint={info.get('xtts_model_path')}\n"
                f"  reference={info.get('xtts_reference_wav')}\n"
                f"  sha256={info.get('xtts_checkpoint_sha256')}\n"
                f"  device={info.get('device')}\n"
                f"  gpu={info.get('gpu')}\n"
                f"  half={info.get('half')}\n"
                f"  PID={worker_pid}"
            )
        except XttsError as e:
            with self._state_lock:
                self._state = "CRASHED"
                self._cooldown_until = time.monotonic() + self._cooldown_duration
            self._last_telemetry["ready"] = False
            self._last_telemetry["state"] = "CRASHED"
            self._last_telemetry["error"] = str(e)
            self._safe_log("error", f"❌ [LocalXttsEngine] XTTS başlatılamadı (CRASHED -> COOLDOWN {self._cooldown_duration:.0f}s): {e}")
            with self._state_lock:
                self._state = "COOLDOWN"
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
                    self._cooldown_until = time.monotonic() + self._cooldown_duration
                self._last_telemetry["ready"] = False
                self._last_telemetry["state"] = "CRASHED"
                self._last_telemetry["error"] = str(exc)
                self._safe_log("error", f"❌ [LocalXttsEngine] XTTS worker süreci çökmüş! Cooldown başlatıldı ({self._cooldown_duration:.0f}s).")
                with self._state_lock:
                    self._state = "COOLDOWN"
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
        info["xtts_reference_wav"] = self.client.info.get("xtts_reference_wav", self.ft_paths.get("speaker_wav", self.speaker_wav))
        info["xtts_model_path"] = self.client.info.get("xtts_model_path", self.ft_paths.get("checkpoint", self.client.model))
        info["xtts_checkpoint_sha256"] = self.client.info.get("xtts_checkpoint_sha256", "none")
        info["is_finetuned"] = bool(self.ft_paths.get("checkpoint_exists", False))
        info["xtts_batch_size"] = self.client.info.get("batch_size", getattr(self.client, "batch_size", 1))
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
