#!/usr/bin/env python3
"""ASTRO V1 — Local Coqui XTTS v2 Engine running on CUDA GPU (cuda:0, FP16).

Implements BaseTTSEngine to provide persistent, sub-second local fallback synthesis
with cached speaker conditioning latents and zero-copy int16 PCM output.
"""

import os
import logging

_LOG = logging.getLogger(__name__)

import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from astro_audio.base_tts_engine import BaseTTSEngine
from astro_audio.xtts_client import XttsClient, XttsError
from astro_audio.memory_guard import get_system_memory_guard, SystemMemoryGuard


def resolve_xtts_home(preferred_home: str = "") -> str:
    """Finds existing XTTS home directory containing virtualenv and Coqui TTS."""
    candidates = [
        preferred_home,
        os.getenv("TTS_XTTS_HOME", ""),
        os.path.expanduser("~/.astro/tts"),
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
        os.path.join(root_dir, "models", "xtts_finetune_ready_v2", "reference.wav"),
        os.path.expanduser("~/.astro/models/xtts_finetune_ready_v2/reference.wav"),
        os.path.abspath("./models/xtts_finetune_ready_v2/reference.wav"),
    ])

    try:
        from ament_index_python.packages import get_package_share_directory
        share_wav = os.path.join(get_package_share_directory("astro_audio"), "voices", "astro.wav")
        candidates.append(share_wav)
    except Exception as _exc:
        _LOG.debug("resolve_xtts_speaker_wav: yok sayılan hata (%s)", _exc)

    # Source and install directory candidates
    candidates.extend([
        os.path.join(root_dir, "ros2_ws", "src", "astro_audio", "voices", "astro.wav"),
        os.path.join(root_dir, "ros2_ws", "install", "astro_audio", "share", "astro_audio", "voices", "astro.wav"),
        os.path.expanduser("~/.astro/tts/Recording.wav"),
        os.path.expanduser("~/.astro/tts/voices/astro.wav"),
        os.path.expanduser("~/.astro/voices/astro.wav"),
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


_PERMANENT_S = 10.0 ** 9  # "asla süresi dolmasın" işareti


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
        mock: bool = False,
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

        self.memory_guard = get_system_memory_guard()
        self.runtime_enabled = os.getenv("TTS_XTTS_ENABLED", "0").lower() in ("1", "true", "yes")
        self._state = "STOPPED" if self.runtime_enabled else "DISABLED"
        self._state_lock = threading.Lock()
        self._cooldown_duration = float(os.getenv("XTTS_COOLDOWN_S", "60.0"))
        self._cooldown_until = 0.0
        # DEGRADED (kabul reddi) de COOLDOWN gibi süreli olmalı. Aksi hâlde açılış
        # telaşında verilen tek bir "bellek yetersiz" kararı sürecin ömrü boyunca
        # kilitleniyor ve bellek sonradan boşalsa bile XTTS bir daha denenmiyordu.
        self._degraded_duration = float(os.getenv("XTTS_DEGRADED_RETRY_S", "120.0"))
        self._degraded_until = 0.0
        # İlk yeniden deneme kısa: açılışta kamera/ONNX/Whisper aynı anda yüklenirken
        # ölçülen bellek tepe noktasıdır, ~20 sn sonra sistem rahatlar.
        self._first_retry_delay = float(os.getenv("XTTS_FIRST_RETRY_S", "20.0"))
        self._max_retries = int(float(os.getenv("XTTS_MAX_ADMISSION_RETRIES", "10")))
        self._retry_count = 0
        self._consecutive_failures = 0
        self._next_retry_delay = 0.0
        self._supervisor: Optional[threading.Thread] = None
        self._supervisor_stop = threading.Event()

        mem_snap = self.memory_guard.get_memory_snapshot()
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
            "xtts_admission_decision": "PENDING",
            "xtts_admission_reject_reason": "none",
            "xtts_queue_wait_ms": 0.0,
            "xtts_model_load_ms": 0.0,
            "xtts_infer_ms": 0.0,
            "xtts_ttfa_ms": 0.0,
            "xtts_total_ms": 0.0,
            "fallback_reason": "none",
        }
        self._last_telemetry.update(mem_snap)

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
            now_m = time.monotonic()
            if self._state == "COOLDOWN" and now_m >= self._cooldown_until:
                self._state = "STOPPED"
            elif self._state == "DEGRADED" and now_m >= self._degraded_until:
                self._state = "STOPPED"
            return self._state

    def _arm_supervisor(self, delay_s: float) -> None:
        """XTTS reddedildikten/çöktükten sonra kendini toparlama döngüsünü başlatır.

        Çağıran `_state_lock`'u tutuyor olabilir; bu yüzden burada kilit alınmaz ve
        hiçbir şey beklenmez. Aynı anda tek bir denetleyici iş parçacığı yaşar ve
        deneme sayısı sınırlıdır — upstream'in kaçınmak istediği "retry storm" oluşmaz.
        Döngü içinden tekrar çağrılırsa yalnızca bir sonraki bekleme süresini günceller.
        """
        if self._supervisor_stop.is_set():
            return
        self._next_retry_delay = max(1.0, delay_s)
        if self._supervisor is not None and self._supervisor.is_alive():
            return

        def _loop():
            while not self._supervisor_stop.is_set():
                if self.memory_guard.is_oom_quarantined:
                    self._safe_log(
                        "warn",
                        "⛔ [LocalXttsEngine] OOM karantinası etkin — yeniden deneme durduruldu.",
                    )
                    return
                if self._max_retries > 0 and self._retry_count >= self._max_retries:
                    self._safe_log(
                        "warn",
                        f"⛔ [LocalXttsEngine] Yeniden deneme sınırına ulaşıldı "
                        f"({self._retry_count}/{self._max_retries}). XTTS bu oturumda devre dışı.",
                    )
                    return
                if self._supervisor_stop.wait(self._next_retry_delay):
                    return
                if self.is_ready():
                    return
                self._retry_count += 1
                limit = "∞" if self._max_retries <= 0 else str(self._max_retries)
                self._safe_log(
                    "info",
                    f"🔁 [LocalXttsEngine] XTTS yeniden deneniyor ({self._retry_count}/{limit})...",
                )
                try:
                    self.start()
                except Exception as exc:
                    self._safe_log("warn", f"⚠️ [LocalXttsEngine] Yeniden deneme başarısız: {exc}")
                if self.is_ready():
                    self._safe_log("info", "✅ [LocalXttsEngine] XTTS kendiliğinden toparlandı.")
                    return

        self._supervisor = threading.Thread(target=_loop, daemon=True, name="xtts-supervisor")
        self._supervisor.start()

    def start(self) -> None:
        """Starts the persistent XTTS worker after system resource admission control."""
        if not self.runtime_enabled:
            with self._state_lock:
                self._state = "DISABLED"
                self._last_telemetry["state"] = "DISABLED"
                self._last_telemetry["ready"] = False
            self._safe_log(
                "info",
                "ℹ️ [XTTS] Runtime disabled by production policy\n"
                "  model_retained=True\n"
                "  worker_spawn=False\n"
                "  reason=production_runtime_disabled"
            )
            return

        with self._state_lock:
            if self._state == "READY" and self.client.is_alive and self.client.is_ready:
                self._safe_log("debug", f"LocalXttsEngine is already READY (PID: {getattr(self.client.proc, 'pid', None)}).")
                return
            if self._state == "STARTING" and self.client.is_alive:
                self._safe_log("debug", f"LocalXttsEngine is already in STARTING state (PID: {getattr(self.client.proc, 'pid', None)}). Reusing worker.")
                return
            now_m = time.monotonic()
            if self._state == "DEGRADED" and now_m < self._degraded_until:
                rem_s = self._degraded_until - now_m
                self._safe_log(
                    "warn",
                    f"⛔ [LocalXttsEngine] State is DEGRADED (Memory pressure / OOM quarantine). "
                    f"Spawn refused, {rem_s:.0f}s to re-evaluation. Local offline TTS remains active.",
                )
                return
            if self._state == "COOLDOWN" and now_m < self._cooldown_until:
                rem_s = self._cooldown_until - now_m
                self._safe_log("warn", f"⏳ [LocalXttsEngine] XTTS is in COOLDOWN ({rem_s:.1f}s remaining). Spawn refused.")
                return

            # Resource Admission Control check BEFORE spawning worker subprocess
            admitted, reject_reason, mem_snap = self.memory_guard.check_xtts_admission()
            self._last_telemetry.update(mem_snap)
            self._last_telemetry["xtts_admission_decision"] = "GRANTED" if admitted else "REJECTED"
            self._last_telemetry["xtts_admission_reject_reason"] = reject_reason

            if not admitted:
                retry_delay = self._first_retry_delay if self._retry_count == 0 else self._degraded_duration
                self._degraded_until = time.monotonic() + retry_delay
                self._state = "DEGRADED"
                self._last_telemetry["ready"] = False
                self._last_telemetry["state"] = "DEGRADED"
                self._last_telemetry["error"] = f"admission_rejected: {reject_reason}"
                self._safe_log(
                    "warn",
                    f"⛔ [XTTS Admission Control REJECTED]:\n"
                    f"  reason={reject_reason}\n"
                    f"  available_ram_mb={mem_snap.get('system_available_ram_mb')}\n"
                    f"  swap_used_mb={mem_snap.get('swap_used_mb')}\n"
                    f"  swap_used_percent={mem_snap.get('swap_used_percent')}%\n"
                    f"  action=degraded_mode_local_offline_tts_active\n"
                    f"  retry_in_s={retry_delay:.0f}"
                )
                self._arm_supervisor(retry_delay)
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

            is_ft = bool(info.get("is_finetuned", False))
            model_lbl = info.get("model", "")
            ckpt_path = info.get("checkpoint") or info.get("xtts_model_path")
            ref_path = info.get("reference") or info.get("xtts_reference_wav")
            sha = info.get("sha256") or info.get("xtts_checkpoint_sha256")
            dev = info.get("device")
            gpu = info.get("gpu")
            half_flag = info.get("half")

            # Production Assertion: Only accept verified fine-tuned model
            if not is_ft or model_lbl != "xtts_finetuned" or not ckpt_path or not ref_path or not sha or sha == "none" or dev != "cuda":
                with self._state_lock:
                    self._state = "CRASHED"
                    self._cooldown_until = time.monotonic() + self._cooldown_duration
                self._last_telemetry["ready"] = False
                self._last_telemetry["state"] = "CRASHED"
                err_msg = (
                    f"XTTS READY validation rejected: invalid fine-tuned metadata: "
                    f"model={model_lbl}, is_finetuned={is_ft}, checkpoint={ckpt_path}, "
                    f"reference={ref_path}, sha256={sha}, device={dev}, gpu={gpu}"
                )
                self._last_telemetry["error"] = err_msg
                self._safe_log("error", f"❌ [LocalXttsEngine] {err_msg}")
                raise XttsError(err_msg)

            with self._state_lock:
                self._state = "READY"
            self._last_telemetry.update({
                "gpu_name": gpu or "Orin",
                "gpu_memory_mb": info.get("gpu_memory_mb", 0.0),
                "cuda_available": dev == "cuda",
                "worker_pid": worker_pid,
                "ready": True,
                "state": "READY",
                "model": "xtts_finetuned",
                "is_finetuned": True,
                "xtts_model_path": ckpt_path,
                "xtts_reference_wav": ref_path,
                "xtts_checkpoint_sha256": sha,
                "device": dev,
                "gpu": gpu,
                "half": half_flag,
                "error": "none",
            })
            self._safe_log(
                "info",
                f"✅ [XTTS READY]\n"
                f"  model=xtts_finetuned\n"
                f"  checkpoint={ckpt_path}\n"
                f"  reference={ref_path}\n"
                f"  sha256={sha}\n"
                f"  device={dev}\n"
                f"  gpu={gpu}\n"
                f"  half={half_flag}\n"
                f"  PID={worker_pid}"
            )
        except XttsError as e:
            err_text = str(e).lower()
            proc_code = getattr(self.client.proc, "returncode", None) if self.client.proc else None
            is_kernel_oom = (proc_code in (-9, 137, -15))
            is_cuda_alloc_fail = "cuda_allocation_failure" in err_text or any(k in err_text for k in ("cudasynchronize", "cudacachingallocator", "nvmapmemalloc", "error 12", "nvml_success"))

            if is_kernel_oom:
                self.memory_guard.record_oom_kill(pid=getattr(self.client.proc, "pid", None), details=str(e))
                with self._state_lock:
                    self._degraded_until = time.monotonic() + _PERMANENT_S
                    self._state = "DEGRADED"
                self._last_telemetry["state"] = "DEGRADED"
                self._last_telemetry["ready"] = False
                self._last_telemetry["error"] = f"oom_killed (exit_code={proc_code})"
                self._last_telemetry["fallback_reason"] = "OOM_KERNEL_KILL"
                self._safe_log(
                    "error",
                    f"🚨 [XTTS OOM KILL DETECTED]: Worker process terminated by Linux OOM Killer (exit_code={proc_code})!\n"
                    f"⛔ [XTTS Retry Storm Prevented]: XTTS permanently set to DEGRADED for this session.\n"
                    f"🛡️ [Critical Path Shielded]: Realtime audio, STT, LLM, and local offline TTS remain fully functional."
                )
            elif is_cuda_alloc_fail:
                with self._state_lock:
                    self._degraded_until = time.monotonic() + self._cooldown_duration
                    self._state = "DEGRADED"
                self._last_telemetry["state"] = "DEGRADED"
                self._last_telemetry["ready"] = False
                self._last_telemetry["error"] = f"cuda_allocation_failure: {e}"
                self._last_telemetry["fallback_reason"] = "CUDA_ALLOCATION_FAILURE"
                self._safe_log(
                    "error",
                    f"🚨 [XTTS CUDA ALLOCATION FAILURE DETECTED]: PyTorch CUDA Allocator / NvMap allocation error: {e}\n"
                    f"⚠️ [Emergency Fallback Triggered]: Transitioning to DEGRADED mode for {self._cooldown_duration:.0f}s. Emergency TTS activated instantly."
                )
                with self._state_lock:
                    self._arm_supervisor(self._cooldown_duration + 1.0)
            else:
                with self._state_lock:
                    self._state = "CRASHED"
                    self._cooldown_until = time.monotonic() + self._cooldown_duration
                self._last_telemetry["ready"] = False
                self._last_telemetry["state"] = "CRASHED"
                self._last_telemetry["error"] = str(e)
                self._last_telemetry["fallback_reason"] = "UNKNOWN"
                self._safe_log("error", f"❌ [LocalXttsEngine] XTTS başlatılamadı (CRASHED -> COOLDOWN {self._cooldown_duration:.0f}s): {e}")
                with self._state_lock:
                    self._state = "COOLDOWN"
                    self._arm_supervisor(self._cooldown_duration + 1.0)
            raise

    def is_ready(self) -> bool:
        with self._state_lock:
            if not getattr(self, "runtime_enabled", False) and self._state != "READY":
                return False
            return self._state == "READY" and (self.client.is_ready or getattr(self.client, "is_alive", False))

    def is_healthy(self) -> bool:
        if not self.is_ready():
            return False
        with self._state_lock:
            if self._state in ("DEGRADED", "TIMEOUT", "FAILED", "QUARANTINED", "CRASHED", "COOLDOWN", "DISABLED"):
                return False
        if self._consecutive_failures > 0:
            return False
        last_infer = self._last_telemetry.get("last_infer_ms", 0.0)
        if last_infer > 5000.0:
            return False
        return True

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

        # Pre-synthesis assertion: Ensure model is strictly verified fine-tuned
        if not self._last_telemetry.get("is_finetuned"):
            self._safe_log("error", "❌ [LocalXttsEngine] Sentez iptal: Fine-tuned model doğrulanmadı!")
            return None

        t_start = time.perf_counter()
        synth_timeout = float(os.getenv("TTS_XTTS_SYNTHESIS_TIMEOUT_S", "8.0"))
        try:
            res = self.client.synthesize_chunk(
                text=text,
                generation_id=generation_id,
                return_pcm=True,
                language=language or self.language,
                timeout=synth_timeout,
            )

            if res.get("cancelled") or not res.get("ok"):
                self._consecutive_failures += 1
                return None

            pcm_bytes = res.get("pcm_bytes")
            tot_ms = (time.perf_counter() - t_start) * 1000.0
            gpu_ms = res.get("gpu_inference_ms", tot_ms)
            q_wait = max(0.0, tot_ms - gpu_ms)
            rtf = res.get("rtf", 0.0)
            vram = res.get("gpu_memory_mb", 0.0)

            self._consecutive_failures = 0
            self._last_telemetry.update({
                "xtts_queue_wait_ms": round(q_wait, 1),
                "xtts_model_load_ms": 0.0,
                "xtts_infer_ms": round(gpu_ms, 1),
                "xtts_ttfa_ms": round(tot_ms, 1),
                "xtts_total_ms": round(tot_ms, 1),
                "last_infer_ms": round(gpu_ms, 1),
                "rtf": rtf,
                "gpu_memory_mb": vram,
                "ready": True,
                "state": "READY",
                "fallback_reason": "none",
            })

            return pcm_bytes

        except Exception as exc:
            self._consecutive_failures += 1
            tot_ms = (time.perf_counter() - t_start) * 1000.0
            is_timeout = "timed out" in str(exc).lower()
            self._last_telemetry["fallback_reason"] = "xtts_timeout" if is_timeout else str(exc)

            if is_timeout:
                self._safe_log("warn", f"⏳ [LocalXttsEngine] XTTS sentez zaman aşımı ({tot_ms:.0f}ms > {synth_timeout:.0f}s): {exc} — Worker canlı tutuluyor, XTTS 30s DEGRADED moduna alınıyor, acil fallback devreye giriyor.")
                with self._state_lock:
                    self._degraded_until = time.monotonic() + 30.0
                    self._state = "DEGRADED"
                self._last_telemetry["ready"] = False
                self._last_telemetry["state"] = "DEGRADED"
                self._last_telemetry["error"] = f"fallback_reason=xtts_timeout ({exc})"
                return None

            self._safe_log("warn", f"⚠️ [LocalXttsEngine] Sentez hatası: {exc}")
            if not self.client.is_alive:
                proc_code = getattr(self.client.proc, "returncode", None) if self.client.proc else None
                is_oom = (proc_code in (-9, 137, -15))
                if is_oom:
                    self.memory_guard.record_oom_kill(pid=getattr(self.client.proc, "pid", None), details=str(exc))
                    with self._state_lock:
                        self._degraded_until = time.monotonic() + _PERMANENT_S
                        self._state = "DEGRADED"
                    self._last_telemetry["state"] = "DEGRADED"
                    self._last_telemetry["ready"] = False
                    self._last_telemetry["error"] = f"oom_killed (exit_code={proc_code})"
                    self._safe_log("error", f"🚨 [LocalXttsEngine] XTTS worker OOM killed (exit_code={proc_code}) during synthesis! Transitioning to DEGRADED.")
                else:
                    with self._state_lock:
                        self._state = "CRASHED"
                        self._cooldown_until = time.monotonic() + self._cooldown_duration
                    self._last_telemetry["ready"] = False
                    self._last_telemetry["state"] = "CRASHED"
                    self._last_telemetry["error"] = str(exc)
                    self._safe_log("error", f"❌ [LocalXttsEngine] XTTS worker süreci çökmüş! Cooldown başlatıldı ({self._cooldown_duration:.0f}s).")
                    with self._state_lock:
                        self._state = "COOLDOWN"
                        self._arm_supervisor(self._cooldown_duration + 1.0)
            return None

    def _try_auto_restart(self) -> None:
        try:
            with self._state_lock:
                if self._state == "DEGRADED":
                    self._safe_log("warn", "⛔ [LocalXttsEngine] Auto-restart skipped: XTTS is in DEGRADED state.")
                    return
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
        worker_pid = self.client.proc.pid if self.client.proc else None
        mem_snap = self.memory_guard.get_memory_snapshot(xtts_pid=worker_pid)
        info.update(mem_snap)
        if self.client.ready_info:
            info.update(self.client.ready_info)
        if worker_pid:
            info["worker_pid"] = worker_pid
        is_ready_val = self.is_ready()
        is_ft = bool(self.client.ready_info.get("is_finetuned", self.ft_paths.get("checkpoint_exists", False)))
        info["ready"] = is_ready_val
        info["is_finetuned"] = is_ft
        info["model"] = "xtts_finetuned" if is_ft else "none"
        info["xtts_reference_wav"] = self.client.ready_info.get("reference") or self.client.ready_info.get("xtts_reference_wav", self.ft_paths.get("speaker_wav", self.speaker_wav))
        info["xtts_model_path"] = self.client.ready_info.get("checkpoint") or self.client.ready_info.get("xtts_model_path", self.ft_paths.get("checkpoint", self.client.model))
        info["xtts_checkpoint_sha256"] = self.client.ready_info.get("sha256") or self.client.ready_info.get("xtts_checkpoint_sha256", "none")
        info["xtts_batch_size"] = self.client.ready_info.get("batch_size", getattr(self.client, "batch_size", 1))
        info["xtts_admission_decision"] = self._last_telemetry.get("xtts_admission_decision", "GRANTED" if is_ready_val else "REJECTED")
        info["xtts_admission_reject_reason"] = self._last_telemetry.get("xtts_admission_reject_reason", "none")
        with self._state_lock:
            info["state"] = self._state
        return info

    def stop(self) -> None:
        # Bekleyen yeniden denemeyi iptal et; aksi hâlde kapanıştan sonra
        # denetleyici uyanıp worker'ı yeniden başlatmaya çalışırdı.
        self._supervisor_stop.set()
        with self._state_lock:
            self._state = "STOPPING"
        self.client.stop()
        with self._state_lock:
            self._state = "STOPPED"
        self._last_telemetry["ready"] = False
        self._last_telemetry["state"] = "STOPPED"
