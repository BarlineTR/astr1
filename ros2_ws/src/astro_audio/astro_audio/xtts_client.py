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
        batch_size: int = 4,
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
        self.batch_size = batch_size
        self.model = model
        self._log = logger or (lambda level, msg: None)

        self.custom_model = self._resolve_custom_model(model_dir, checkpoint, config, vocab, speakers)

        self.proc: Optional[subprocess.Popen] = None
        self.info: Dict[str, Any] = {}
        self._responses = queue.Queue()
        self._ready = threading.Event()
        self._startup_error: Optional[str] = None
        self._req_lock = threading.Lock()
        self._lifecycle_lock = threading.Lock()
        self._req_id = 0
        self._current_gen_id = 0

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
                "/home/okistech/Desktop/astr1/models/xtts_finetune_ready_v2",
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
                "--speaker-wav", self.speaker_wav,
                "--language", self.language,
                "--device", self.device,
                "--half", "1" if self.half else "0",
                "--batch-size", str(self.batch_size),
                "--model", self.model,
                "--temperature", str(os.getenv("TTS_XTTS_TEMPERATURE", "0.50")),
                "--length-penalty", str(os.getenv("TTS_XTTS_LENGTH_PENALTY", "1.0")),
                "--repetition-penalty", str(os.getenv("TTS_XTTS_REPETITION_PENALTY", "4.0")),
                "--top-k", str(os.getenv("TTS_XTTS_TOP_K", "45")),
                "--top-p", str(os.getenv("TTS_XTTS_TOP_P", "0.65")),
                "--speed", str(os.getenv("TTS_XTTS_SPEED", "1.05")),
            ]

            if self.custom_model:
                for key, flag in (("checkpoint", "--checkpoint"), ("config", "--config"),
                                  ("vocab", "--vocab"), ("speakers", "--speakers")):
                    if self.custom_model.get(key):
                        cmd += [flag, str(self.custom_model[key])]

            self._cmd = cmd
            self._stderr_lines = []

            env = os.environ.copy()
            # Preserve system CUDA paths for Jetson Orin Nano
            pkg_dir = str(Path(__file__).parent.parent)
            env["PYTHONPATH"] = pkg_dir + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
            env["PYTHONNOUSERSITE"] = "1"
            env["COQUI_TOS_AGREED"] = "1"
            env["PATH"] = f"{self.python_path.parent}{os.pathsep}{env.get('PATH', '')}"
            env["VIRTUAL_ENV"] = str(self.python_path.parent.parent)

            # Preserve CUDA and Torch library locations
            cuda_lib = "/usr/local/cuda/lib64"
            if os.path.exists(cuda_lib):
                env["LD_LIBRARY_PATH"] = cuda_lib + (os.pathsep + env.get("LD_LIBRARY_PATH", "") if env.get("LD_LIBRARY_PATH") else "")

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
            if event == "ready":
                self.info = msg
                self._ready.set()
            elif event == "error":
                self._startup_error = f"{msg.get('stage')}: {msg.get('message')}"
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
        if self._startup_error:
            stderr_snippet = "\n".join(self._stderr_lines[-20:]) if self._stderr_lines else "None"
            raise XttsError(f"XTTS startup failed: {self._startup_error}. Stderr: {stderr_snippet}")
        if not self.info:
            code = self.returncode
            stderr_snippet = "\n".join(self._stderr_lines[-30:]) if self._stderr_lines else "None"
            cmd_str = " ".join(getattr(self, "_cmd", []))
            self._safe_log(
                "error",
                f"🚨 [XTTS Worker Crash Diagnostics]:\n"
                f"  exit_code={code}\n"
                f"  argv={cmd_str}\n"
                f"  cwd={self.home}\n"
                f"  python_path={self.python_path}\n"
                f"  checkpoint={self.custom_model.get('checkpoint') if self.custom_model else 'default'}\n"
                f"  config={self.custom_model.get('config') if self.custom_model else 'default'}\n"
                f"  vocab={self.custom_model.get('vocab') if self.custom_model else 'default'}\n"
                f"  speakers={self.custom_model.get('speakers') if self.custom_model else 'default'}\n"
                f"  speaker_wav={self.speaker_wav}\n"
                f"  startup_error={self._startup_error}\n"
                f"  stderr:\n{stderr_snippet}"
            )
            raise XttsError(f"XTTS worker exited unexpectedly (code {code}):\n{stderr_snippet}")
        return self.info

    @property
    def is_ready(self) -> bool:
        return bool(self.info) and self.is_alive

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
                except Exception:
                    pass

    def synthesize_chunk(
        self,
        text: str,
        generation_id: int = 0,
        return_pcm: bool = True,
        out_path: Optional[str] = None,
        timeout: float = 30.0,
        language: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Synthesizes text clause and returns dictionary containing raw PCM bytes and telemetry."""
        if not self.is_alive:
            raise XttsError(f"XTTS worker is not alive (code {self.returncode})")

        with self._req_lock:
            if generation_id > 0 and generation_id < self._current_gen_id:
                return {"ok": False, "cancelled": True, "message": "Superseded generation"}

            self._req_id += 1
            req_id = self._req_id
            req = {
                "id": req_id,
                "gen_id": generation_id,
                "text": text,
                "out": os.path.abspath(str(out_path)) if out_path else "",
                "return_pcm": return_pcm,
                "language": language or self.language,
            }

            try:
                self.proc.stdin.write(json.dumps(req, ensure_ascii=False) + "\n")
                self.proc.stdin.flush()
            except (BrokenPipeError, ValueError) as exc:
                raise XttsError(f"Failed writing to XTTS worker: {exc}") from exc

            while True:
                try:
                    msg = self._responses.get(timeout=timeout)
                except queue.Empty as exc:
                    raise XttsError(f"XTTS timed out after {timeout:.1f}s") from exc
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
            except Exception:
                pass
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
                except Exception:
                    pass

            # If still running after quit command, send SIGTERM
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=1.5)
                except subprocess.TimeoutExpired:
                    pass

            # If still running after SIGTERM, send SIGKILL
            if proc.poll() is None:
                proc.kill()
                try:
                    proc.wait(timeout=1.5)
                except subprocess.TimeoutExpired:
                    pass
        except Exception as e:
            self._safe_log("warn", f"Notice while stopping XTTS worker: {e}")
        finally:
            self.proc = None
            self.info = {}
            self._ready.clear()
            self._startup_error = None
