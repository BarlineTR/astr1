#!/usr/bin/env python3
"""ASTRO V1 — High-Performance XTTS Worker Client.

Manages the persistent worker process (`xtts_worker.py`) running in the dedicated
XTTS virtual environment with CUDA GPU acceleration.

Features:
  - Sub-second clause-level synthesis with direct int16 PCM memory return
  - Generational barge-in cancellation
  - Cached speaker conditioning latent support
  - Detailed GPU memory and inference telemetry
"""

import base64
import json
import os
import queue
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

PREFIX = "@@XTTS@@ "
DEFAULT_HOME = os.path.expanduser("~/.astro/tts")

CUSTOM_MODEL_FILES = {
    "checkpoint": "model.pth",
    "config": "config.json",
    "vocab": "vocab.json",
    "speakers": "speakers_xtts.pth",
}
OPTIONAL_MODEL_FILES = ("speakers",)


def _env_float(name: str, default: float, lo: float, hi: float) -> float:
    """Reads a float tuning knob from the environment, clamped to the model's valid range."""
    try:
        return min(hi, max(lo, float(os.getenv(name, "").strip() or default)))
    except ValueError:
        return default


def _env_int(name: str, default: int, lo: int, hi: int) -> int:
    try:
        return min(hi, max(lo, int(float(os.getenv(name, "").strip() or default))))
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on", "evet")


def load_inference_params() -> Dict[str, Any]:
    """Builds the XTTS decoder tuning payload from TTS_XTTS_* environment variables.

    These mirror the "Advanced settings" panel of the Coqui XTTS demo UI and are sent
    with every synthesis request, so editing .env is enough to retune the voice.
    """
    return {
        "temperature": _env_float("TTS_XTTS_TEMPERATURE", 0.75, 0.0, 1.0),
        "length_penalty": _env_float("TTS_XTTS_LENGTH_PENALTY", 1.0, -10.0, 10.0),
        "repetition_penalty": _env_float("TTS_XTTS_REPETITION_PENALTY", 5.0, 1.0, 10.0),
        "top_k": _env_int("TTS_XTTS_TOP_K", 50, 1, 100),
        "top_p": _env_float("TTS_XTTS_TOP_P", 0.85, 0.0, 1.0),
        "speed": _env_float("TTS_XTTS_SPEED", 1.05, 0.5, 2.0),
        "enable_text_splitting": _env_bool("TTS_XTTS_TEXT_SPLITTING", False),
    }


class XttsError(RuntimeError):
    """Worker failed to start or synthesis failed."""


class XttsClient:
    """Persistent, thread-safe client managing the high-performance XTTS GPU worker."""

    def __init__(
        self,
        speaker_wav: str,
        home: Optional[str] = None,
        language: str = "tr",
        device: str = "cuda",
        half: bool = True,
        batch_size: Optional[int] = None,
        model: str = "tts_models/multilingual/multi-dataset/xtts_v2",
        model_dir: Optional[str] = None,
        checkpoint: Optional[str] = None,
        config: Optional[str] = None,
        vocab: Optional[str] = None,
        speakers: Optional[str] = None,
        logger=None,
    ):
        self.home = Path(os.path.expanduser(home or os.getenv("TTS_XTTS_HOME") or DEFAULT_HOME))
        self.speaker_wav = os.path.abspath(os.path.expanduser(str(speaker_wav)))
        self.language = language
        self.device = device
        self.half = half
        self.batch_size = batch_size if batch_size is not None else int(os.getenv("TTS_XTTS_BATCH_SIZE", "1"))
        self.model = model
        self._log = logger or (lambda level, msg: None)

        self.custom_model = self._resolve_custom_model(model_dir, checkpoint, config, vocab, speakers)

        self.proc: Optional[subprocess.Popen] = None
        self.probe_info: Dict[str, Any] = {}
        self.ready_info: Dict[str, Any] = {}
        self.info: Dict[str, Any] = {}
        self._stderr_lines: List[str] = []
        self._last_error_event: Optional[Dict[str, Any]] = None
        self._cmd: List[str] = []
        self._responses = queue.Queue()
        self._ready = threading.Event()
        self._startup_error: Optional[str] = None
        self._req_lock = threading.Lock()
        self._lifecycle_lock = threading.Lock()
        self._req_id = 0
        self._current_gen_id = 0
        self.inference_params = load_inference_params()

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

    @staticmethod
    def _resolve_custom_model(model_dir, checkpoint, config, vocab, speakers):
        explicit = {
            "checkpoint": checkpoint or os.getenv("TTS_XTTS_CHECKPOINT"),
            "config": config or os.getenv("TTS_XTTS_CONFIG"),
            "vocab": vocab or os.getenv("TTS_XTTS_VOCAB"),
            "speakers": speakers or os.getenv("TTS_XTTS_SPEAKERS"),
        }
        resolved_model_dir = model_dir or os.getenv("TTS_XTTS_MODEL_DIR")
        if not resolved_model_dir and explicit.get("checkpoint"):
            resolved_model_dir = str(Path(os.path.expanduser(explicit["checkpoint"])).parent)

        if not resolved_model_dir and not any(explicit.values()):
            # Auto-discover standard fine-tuned model directories if present on system
            candidates = [
                os.path.abspath("./models/xtts_finetune_ready_v2"),
                os.path.expanduser("~/.astro/models/xtts_finetune_ready_v2"),
                os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "models", "xtts_finetune_ready_v2")),
            ]
            for cand in candidates:
                if os.path.exists(cand) and os.path.exists(os.path.join(cand, "model.pth")):
                    resolved_model_dir = cand
                    break

        if not resolved_model_dir and not any(explicit.values()):
            return None

        resolved = {}
        base = Path(os.path.expanduser(resolved_model_dir)) if resolved_model_dir else None
        for key, filename in CUSTOM_MODEL_FILES.items():
            given = explicit.get(key)
            if given:
                resolved[key] = os.path.abspath(os.path.expanduser(given))
            elif base is not None:
                path = str((base / filename).absolute())
                resolved[key] = None if (key in OPTIONAL_MODEL_FILES and not os.path.exists(path)) else path
            else:
                resolved[key] = None
        return resolved

    def _check_custom_model(self):
        if not self.custom_model:
            return None
        for key, path in self.custom_model.items():
            if not path:
                if key in OPTIONAL_MODEL_FILES:
                    continue
                return f"Özel XTTS modeli eksik: {key} yolu verilmedi"
            if not os.path.exists(path):
                return f"Özel XTTS modeli dosyası bulunamadı: {path}"
        return None

    @property
    def python_path(self) -> Path:
        return self.home / ".venv" / "bin" / "python"

    @property
    def worker_path(self) -> Path:
        return Path(__file__).with_name("xtts_worker.py")

    def check_install(self) -> Optional[str]:
        if not self.home.exists():
            return f"XTTS dizini yok: {self.home} — ./scripts/install_xtts.sh çalıştırın"
        if not self.python_path.exists():
            return f"XTTS venv'i yok: {self.python_path} — ./scripts/install_xtts.sh çalıştırın"
        if not os.path.exists(self.speaker_wav):
            return f"Referans ses dosyası yok: {self.speaker_wav}"
        if not self.worker_path.exists():
            return f"İşçi betiği bulunamadı: {self.worker_path}"
        return self._check_custom_model()

    def start(self) -> None:
        """Starts the persistent XTTS worker subprocess, guaranteeing single-process ownership."""
        with self._lifecycle_lock:
            # 1. If already alive and ready OR alive and in progress of starting, reuse existing worker!
            if self.is_alive:
                if self.is_ready:
                    self._safe_log("debug", f"XTTS worker already running (PID {self.proc.pid}).")
                    return
                self._safe_log("debug", f"XTTS worker is currently starting (PID {self.proc.pid}). Waiting for initialization.")
                return

            # 2. Ensure any lingering or crashed process is fully stopped first
            if self.proc is not None:
                self.stop()

            problem = self.check_install()
            if problem:
                raise XttsError(problem)

            cmd = [
                str(self.python_path),
                str(self.worker_path),
                "--speaker-wav", str(self.speaker_wav),
            ]

            if self.custom_model and self.custom_model.get("checkpoint"):
                for key, flag in (("checkpoint", "--checkpoint"), ("config", "--config"),
                                  ("vocab", "--vocab"), ("speakers", "--speakers")):
                    if self.custom_model.get(key):
                        cmd += [flag, str(self.custom_model[key])]
            else:
                cmd += ["--model", str(self.model)]

            cmd += [
                "--language", self.language,
                "--device", self.device,
                "--half", "1" if self.half else "0",
                "--batch-size", str(self.batch_size),
                "--temperature", str(os.getenv("TTS_XTTS_TEMPERATURE", "0.50")),
                "--length-penalty", str(os.getenv("TTS_XTTS_LENGTH_PENALTY", "1.0")),
                "--repetition-penalty", str(os.getenv("TTS_XTTS_REPETITION_PENALTY", "4.0")),
                "--top-k", str(os.getenv("TTS_XTTS_TOP_K", "45")),
                "--top-p", str(os.getenv("TTS_XTTS_TOP_P", "0.65")),
                "--speed", str(os.getenv("TTS_XTTS_SPEED", "1.05")),
            ]
            if os.getenv("TTS_XTTS_NO_WARMUP", "1") not in ("0", "false", "False"):
                cmd.append("--no-warmup")

            self._cmd = cmd
            self._stderr_lines = []
            self._last_error_event = None

            env = os.environ.copy()
            # Clean and isolate PYTHONPATH to active workspace and system ROS2
            pkg_dir = str(Path(__file__).parent.parent.resolve())
            raw_pp = env.get("PYTHONPATH", "")
            cleaned_paths = [pkg_dir]
            seen = {pkg_dir}
            for p in raw_pp.split(os.pathsep):
                p_str = p.strip()
                if not p_str or not os.path.exists(p_str):
                    continue
                p_norm = str(Path(p_str).resolve())
                # Exclude duplicate or legacy workspace build/install paths outside ros2_ws
                if "/astr1/install" in p_norm or "/astr1/build" in p_norm:
                    if not ("/ros2_ws/install" in p_norm or "/ros2_ws/build" in p_norm):
                        continue
                if p_norm not in seen:
                    cleaned_paths.append(p_str)
                    seen.add(p_norm)

            env["PYTHONPATH"] = os.pathsep.join(cleaned_paths)
            env["PYTHONNOUSERSITE"] = "1"
            env["COQUI_TOS_AGREED"] = "1"
            env["PATH"] = f"{self.python_path.parent}{os.pathsep}{env.get('PATH', '')}"
            env["VIRTUAL_ENV"] = str(self.python_path.parent.parent)

            # Sanitize CUDA_VISIBLE_DEVICES (remove empty or 'all' to ensure native Jetson Orin device discovery)
            cvd = os.getenv("CUDA_VISIBLE_DEVICES")
            if cvd is None or cvd.strip().lower() in ("", "all", "none"):
                env.pop("CUDA_VISIBLE_DEVICES", None)
            else:
                env["CUDA_VISIBLE_DEVICES"] = cvd.strip()

            self._safe_log(
                "info",
                f"📌 [XTTS CUDA ENV]\n"
                f"  CUDA_VISIBLE_DEVICES={env.get('CUDA_VISIBLE_DEVICES', '<unset>')}\n"
                f"  python_executable={self.python_path}\n"
                f"  worker_path={self.worker_path}\n"
                f"  speaker_wav={self.speaker_wav}"
            )

            # STAGE 1: Log Pre-Start Hardware & Memory Snapshot
            try:
                import psutil
                mem = psutil.virtual_memory()
                self._safe_log(
                    "info",
                    f"📊 [XTTS Memory Snapshot - pre_worker_start]: "
                    f"sys_avail_mb={round(mem.available / (1024 * 1024), 1)} | "
                    f"sys_total_mb={round(mem.total / (1024 * 1024), 1)} | "
                    f"sys_percent={mem.percent}%"
                )
            except Exception as _exc:
                self._safe_log("debug", f"start: yok sayılan hata ({_exc})")

            self._ready.clear()
            self._startup_error = None
            self.info = {}

            self.proc = subprocess.Popen(
                cmd,
                cwd=str(self.home),
                env=env,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )
            threading.Thread(target=self._read_stdout, daemon=True).start()
            threading.Thread(target=self._read_stderr, daemon=True).start()

    def _read_stdout(self):
        for line in self.proc.stdout:
            line = line.rstrip("\n")
            if not line.startswith(PREFIX):
                if line.strip():
                    self._safe_log("debug", f"[xtts] {line}")
                continue
            try:
                msg = json.loads(line[len(PREFIX):])
            except json.JSONDecodeError:
                self._safe_log("warn", f"[xtts] JSON parsing error: {line}")
                continue

            event = msg.get("event")
            if event == "probe":
                self.probe_info = msg
                self._safe_log(
                    "info",
                    f"🔍 [XTTS Probe Success]: python={msg.get('python_executable')} | "
                    f"torch={msg.get('torch_version')} | cuda_ver={msg.get('torch_cuda_version')} | "
                    f"torch_cuda_available={msg.get('torch_cuda_available')} | device_count={msg.get('device_count')} | "
                    f"gpu_name={msg.get('device_name')}"
                )
            elif event == "ready":
                is_ft = bool(msg.get("is_finetuned", False))
                model_lbl = msg.get("model", "")
                ckpt_p = msg.get("checkpoint") or msg.get("xtts_model_path")
                sha_v = msg.get("sha256") or msg.get("xtts_checkpoint_sha256")
                dev_v = msg.get("device")

                # Strict fine-tuned metadata gate: Reject generic or incomplete models
                if not is_ft or model_lbl != "xtts_finetuned" or not ckpt_p or not sha_v or sha_v == "none":
                    err_msg = (
                        f"Generic or unverified XTTS model rejected: model={model_lbl}, "
                        f"is_finetuned={is_ft}, checkpoint={ckpt_p}, sha256={sha_v}, device={dev_v}"
                    )
                    self._startup_error = err_msg
                    self._last_error_event = {"event": "error", "stage": "validation", "message": err_msg}
                else:
                    self.ready_info = msg
                    self.info = msg
                self._ready.set()
            elif event == "error":
                self._startup_error = f"{msg.get('stage')}: {msg.get('message')}"
                self._last_error_event = msg
                self._ready.set()
            else:
                self._responses.put(msg)
        self._ready.set()

    def _read_stderr(self):
        for line in self.proc.stderr:
            line = line.rstrip("\n")
            if line.strip():
                self._stderr_lines.append(line)
                if len(self._stderr_lines) > 200:
                    self._stderr_lines = self._stderr_lines[-200:]
                self._safe_log("debug", f"[xtts:err] {line}")

    def wait_ready(self, timeout: float = 180.0) -> Dict[str, Any]:
        if not self._ready.wait(timeout):
            stderr_snippet = "\n".join(self._stderr_lines[-20:]) if self._stderr_lines else "None"
            raise XttsError(f"XTTS did not become ready in {timeout:.0f}s. Stderr: {stderr_snippet}")
        if self._startup_error or not self.ready_info or not self.is_ready:
            if self.proc is not None:
                try:
                    code = self.proc.wait(timeout=1.5)
                except Exception:
                    code = self.proc.poll()
            else:
                code = None
            stderr_snippet = "\n".join(self._stderr_lines[-40:]) if self._stderr_lines else "None"
            cmd_str = " ".join(getattr(self, "_cmd", []))
            probe = self.probe_info if self.probe_info else self.info
            err_diag = (getattr(self, "_last_error_event", None) or {}).get("diagnostics", {})
            self._safe_log(
                "error",
                f"🚨 [XTTS Worker Crash Diagnostics]:\n"
                f"  exit_code={code}\n"
                f"  argv={cmd_str}\n"
                f"  cwd={self.home}\n"
                f"  python_executable={probe.get('python_executable') or err_diag.get('python_executable', self.python_path)}\n"
                f"  torch_version={probe.get('torch_version') or err_diag.get('torch_version', 'unknown')}\n"
                f"  torch_cuda_version={probe.get('torch_cuda_version') or err_diag.get('torch_cuda_version', 'unknown')}\n"
                f"  cuda_available={probe.get('torch_cuda_available', err_diag.get('cuda_available', False))}\n"
                f"  gpu_name={probe.get('device_name') or err_diag.get('gpu_name', 'unknown')}\n"
                f"  free_gpu_memory_mb={probe.get('free_gpu_memory_mb', err_diag.get('free_gpu_memory_mb', 'unknown'))}\n"
                f"  total_gpu_memory_mb={probe.get('total_gpu_memory_mb', err_diag.get('total_gpu_memory_mb', 'unknown'))}\n"
                f"  device_properties={err_diag.get('device_properties', {})}\n"
                f"  PYTHONPATH={probe.get('PYTHONPATH', os.getenv('PYTHONPATH', 'none'))}\n"
                f"  CUDA_VISIBLE_DEVICES={probe.get('CUDA_VISIBLE_DEVICES', os.getenv('CUDA_VISIBLE_DEVICES', 'all'))}\n"
                f"  LD_LIBRARY_PATH={probe.get('LD_LIBRARY_PATH', os.getenv('LD_LIBRARY_PATH', 'none'))}\n"
                f"  checkpoint={self.custom_model.get('checkpoint') if self.custom_model else 'default'}\n"
                f"  startup_error={self._startup_error}\n"
                f"  stderr:\n{stderr_snippet}"
            )
            if self._startup_error:
                raise XttsError(f"XTTS startup failed: {self._startup_error}. Stderr: {stderr_snippet}")
            raise XttsError(f"XTTS worker exited unexpectedly (code {code}):\n{stderr_snippet}")
        return self.ready_info

    @property
    def is_ready(self) -> bool:
        return (
            bool(self.ready_info)
            and self.ready_info.get("event") == "ready"
            and self.ready_info.get("is_finetuned") is True
            and self.is_alive
        )

    @property
    def is_alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    @property
    def returncode(self) -> Optional[int]:
        return None if self.proc is None else self.proc.poll()

    def interrupt(self, generation_id: int) -> None:
        """Sends barge-in cancellation command to worker."""
        with self._req_lock:
            self._current_gen_id = max(self._current_gen_id, generation_id)
            if self.is_alive:
                try:
                    req = {"cmd": "interrupt", "gen_id": generation_id}
                    self.proc.stdin.write(json.dumps(req) + "\n")
                    self.proc.stdin.flush()
                except Exception as _exc:
                    self._safe_log("debug", f"interrupt: yok sayılan hata ({_exc})")

    def synthesize_chunk(
        self,
        text: str,
        generation_id: int = 0,
        return_pcm: bool = True,
        out_path: Optional[str] = None,
        timeout: Optional[float] = None,
        language: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Synthesizes text clause and returns dictionary containing raw PCM bytes and telemetry."""
        if not self.is_alive:
            raise XttsError(f"XTTS worker is not alive (code {self.returncode})")

        ttfa_timeout = float(os.getenv("TTS_XTTS_TTFA_TIMEOUT_S", "2.5"))
        synth_timeout = float(os.getenv("TTS_XTTS_SYNTHESIS_TIMEOUT_S", "8.0"))
        effective_timeout = timeout if timeout is not None else synth_timeout

        with self._req_lock:
            if generation_id > 0 and generation_id < self._current_gen_id:
                return {"ok": False, "cancelled": True, "message": "Superseded generation"}

            self._req_id += 1
            req_id = self._req_id
            req = {
                "id": req_id,
                "gen_id": generation_id,
                "generation_id": generation_id,
                "text": text,
                "out": os.path.abspath(str(out_path)) if out_path else "",
                "return_pcm": return_pcm,
                "language": language or self.language,
                **self.inference_params,
            }

            try:
                self.proc.stdin.write(json.dumps(req, ensure_ascii=False) + "\n")
                self.proc.stdin.flush()
            except (BrokenPipeError, ValueError) as exc:
                raise XttsError(f"Failed writing to XTTS worker: {exc}") from exc

            t_req_start = time.monotonic()
            while True:
                try:
                    msg = self._responses.get(timeout=effective_timeout)
                except queue.Empty as exc:
                    elapsed = time.monotonic() - t_req_start
                    raise XttsError(f"XTTS synthesis timed out after {elapsed:.1f}s (effective_timeout={effective_timeout:.1f}s)") from exc
                if msg.get("id") == req_id:
                    break

        if not msg.get("ok"):
            if msg.get("cancelled"):
                return msg
            raise XttsError(msg.get("message", "Unknown synthesis error"))

        pcm_bytes = None
        if msg.get("pcm_base64"):
            try:
                pcm_bytes = base64.b64decode(msg["pcm_base64"].encode("ascii"))
            except Exception as _exc:
                self._safe_log("debug", f"synthesize_chunk: yok sayılan hata ({_exc})")
        msg["pcm_bytes"] = pcm_bytes
        return msg

    def stop(self, timeout: float = 3.0) -> None:
        """Gracefully stops and terminates the worker subprocess, ensuring PID is dead."""
        proc = self.proc
        if proc is None:
            return

        self._safe_log("debug", f"Stopping XTTS worker (PID {proc.pid})...")
        try:
            if proc.poll() is None and proc.stdin:
                try:
                    proc.stdin.write(json.dumps({"cmd": "quit"}) + "\n")
                    proc.stdin.flush()
                    proc.wait(timeout=1.5)
                except Exception as _exc:
                    self._safe_log("debug", f"stop: yok sayılan hata ({_exc})")

            # If still running after quit command, send SIGTERM
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=1.5)
                except subprocess.TimeoutExpired as _exc:
                    self._safe_log("debug", f"stop: yok sayılan hata ({_exc})")

            # If still running after SIGTERM, send SIGKILL
            if proc.poll() is None:
                proc.kill()
                try:
                    proc.wait(timeout=1.5)
                except subprocess.TimeoutExpired as _exc:
                    self._safe_log("debug", f"stop: yok sayılan hata ({_exc})")
        except Exception as e:
            self._safe_log("warn", f"Notice while stopping XTTS worker: {e}")
        finally:
            self.proc = None
            self.info = {}
            self._ready.clear()
            self._startup_error = None
