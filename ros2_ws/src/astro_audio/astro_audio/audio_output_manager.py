#!/usr/bin/env python3
"""ASTRO V1 — Centralized Single-Owner Audio Output Manager.

Guarantees single ownership of hardware audio playback (ReSpeaker / ALSA / sounddevice)
preventing race conditions or conflicts between tts_node and audio_stream_node.

Features:
  - Streaming PCM playback (24kHz / 16kHz int16) with fast resampling
  - WAV file playback (via sounddevice or aplay)
  - Zero-latency barge-in with Generation ID validation
  - Hardware ALSA / ReSpeaker device auto-detection
  - Thread-safe and non-blocking
"""

import os
import queue
import re
import shutil
import subprocess
import threading
import time
import wave
from typing import Callable, Optional, Tuple

import numpy as np

try:
    import sounddevice as sd
except ImportError:
    sd = None

RESPEAKER_NAME_HINTS = ("respeaker", "uac1", "seeed", "arrayuac", "usb audio")
HW_SAMPLE_RATE = 16000  # ReSpeaker hardware native DAC rate
TARGET_SAMPLE_RATE = 24000
CHANNELS = 1
DTYPE = "int16"


def resample_24k_to_16k(raw_24k_bytes: bytes) -> bytes:
    """Downsamples 24kHz int16 PCM to 16kHz int16 PCM."""
    arr_24k = np.frombuffer(raw_24k_bytes, dtype=np.int16)
    if len(arr_24k) == 0:
        return b""
    n_out = int(len(arr_24k) * (2.0 / 3.0))
    indices = np.linspace(0, len(arr_24k) - 1, n_out)
    arr_16k = np.interp(indices, np.arange(len(arr_24k)), arr_24k.astype(np.float32)).astype(np.int16)
    return arr_16k.tobytes()


def resample_16k_to_24k(raw_16k_bytes: bytes) -> bytes:
    """Upsamples 16kHz int16 PCM to 24kHz int16 PCM."""
    arr_16k = np.frombuffer(raw_16k_bytes, dtype=np.int16)
    if len(arr_16k) == 0:
        return b""
    n_out = int(len(arr_16k) * 1.5)
    indices = np.linspace(0, len(arr_16k) - 1, n_out)
    arr_24k = np.interp(indices, np.arange(len(arr_16k)), arr_16k.astype(np.float32)).astype(np.int16)
    return arr_24k.tobytes()


def find_alsa_respeaker_device() -> str:
    """Finds exact ALSA card name or index for ReSpeaker."""
    try:
        res = subprocess.run(["aplay", "-l"], capture_output=True, text=True, timeout=2.0)
        for line in res.stdout.splitlines():
            if any(k in line.lower() for k in RESPEAKER_NAME_HINTS):
                m = re.search(r"card\s+(\d+):", line)
                if m:
                    return f"plughw:{m.group(1)},0"
    except Exception:
        pass
    return "default"


find_respeaker_alsa_device = find_alsa_respeaker_device


def find_sounddevice_output_index(preferred: str = "") -> Tuple[Optional[int], str]:
    if sd is None:
        return None, "sounddevice kurulu değil"
    try:
        devs = [
            (i, dev.get("name", "?"), dev.get("max_output_channels", 0))
            for i, dev in enumerate(sd.query_devices())
            if dev.get("max_output_channels", 0) > 0
        ]
        if not devs:
            return None, "uygun çıkış cihazı bulunamadı"

        if preferred:
            if preferred.strip().lstrip("-").isdigit():
                idx = int(preferred)
                for i, name, _ in devs:
                    if i == idx:
                        return i, name
            else:
                needle = preferred.strip().lower()
                for i, name, _ in devs:
                    if needle in name.lower():
                        return i, name

        for i, name, _ in devs:
            if any(h in name.lower() for h in RESPEAKER_NAME_HINTS):
                return i, name

        return devs[0][0], devs[0][1]
    except Exception as e:
        return None, str(e)


class AudioOutputManager:
    """Centralized, thread-safe hardware audio playback controller with generation gating."""

    def __init__(
        self,
        preferred_device: str = "",
        on_playback_state_change: Optional[Callable[[bool], None]] = None,
        on_first_audio_callback: Optional[Callable[[int, float], None]] = None,
        logger: Optional[Callable[[str, str], None]] = None,
    ):
        self._log = logger or (lambda lvl, msg: None)
        self._on_state_change = on_playback_state_change
        self._on_first_audio = on_first_audio_callback

        self.alsa_device = find_alsa_respeaker_device()
        self.sd_dev_idx, self.sd_dev_name = find_sounddevice_output_index(preferred_device)
        self.has_aplay = shutil.which("aplay") is not None

        self._play_queue: queue.Queue[Tuple[int, bytes]] = queue.Queue(maxsize=1000)
        self._current_generation = 0
        self._lock = threading.Lock()
        self._is_playing = False
        self._last_playback_time = 0.0
        self._first_audio_emitted_for_gen = -1

        self._current_process: Optional[subprocess.Popen] = None
        self._output_stream = None

        # Dedicated worker thread for sounddevice PCM streaming
        self._worker_thread = threading.Thread(target=self._playback_loop, daemon=True)
        self._worker_thread.start()

        self._log("info", f"🔊 [AudioOutputManager] Başlatıldı | ALSA: [{self.alsa_device}] | Sounddevice: [{self.sd_dev_idx}: {self.sd_dev_name}]")

    @property
    def current_generation(self) -> int:
        with self._lock:
            return self._current_generation

    @property
    def is_playing(self) -> bool:
        return self._is_playing or (time.monotonic() - self._last_playback_time < 0.20)

    def new_generation(self) -> int:
        """Increments generation ID, interrupting any ongoing audio."""
        with self._lock:
            self._current_generation += 1
            gen_id = self._current_generation
            self._flush_queue_locked()
            self._stop_active_processes_locked()
            self._is_playing = False
            self._first_audio_emitted_for_gen = -1

        if self._on_state_change:
            self._on_state_change(False)
        return gen_id

    def interrupt(self, new_generation_id: Optional[int] = None) -> int:
        """Explicit barge-in interrupt."""
        with self._lock:
            if new_generation_id is not None:
                self._current_generation = max(self._current_generation + 1, new_generation_id)
            else:
                self._current_generation += 1
            gen_id = self._current_generation
            self._flush_queue_locked()
            self._stop_active_processes_locked()
            self._is_playing = False

        if self._on_state_change:
            self._on_state_change(False)
        self._log("debug", f"⚡ [AudioOutputManager] Barge-In Interrupt -> Generation: {gen_id}")
        return gen_id

    def play_pcm_chunk(self, pcm_data: bytes, sample_rate: int = 16000, generation_id: Optional[int] = None) -> bool:
        """Enqueues raw int16 PCM data for streaming playback."""
        if not pcm_data:
            return False

        with self._lock:
            gen = generation_id if generation_id is not None else self._current_generation
            if gen < self._current_generation:
                return False  # Stale generation chunk dropped

        # Resample to hardware DAC rate (16000) if needed
        if sample_rate == 24000:
            raw_16k = resample_24k_to_16k(pcm_data)
        elif sample_rate == 16000:
            raw_16k = pcm_data
        else:
            raw_16k = pcm_data

        try:
            self._play_queue.put_nowait((gen, raw_16k))
            return True
        except queue.Full:
            self._log("warn", "⚠️ [AudioOutputManager] Çalma kuyruğu dolu, blok atlandı!")
            return False

    def play_wav_file(self, wav_path: str, generation_id: Optional[int] = None, blocking: bool = False) -> bool:
        """Plays a WAV file through hardware output with generation check."""
        if not os.path.exists(wav_path):
            return False

        with self._lock:
            gen = generation_id if generation_id is not None else self._current_generation
            if gen < self._current_generation:
                return False

        # Read WAV PCM frames and feed into queue
        try:
            with wave.open(wav_path, 'rb') as wf:
                sr = wf.getframerate()
                n_frames = wf.getnframes()
                raw_bytes = wf.readframes(n_frames)
                return self.play_pcm_chunk(raw_bytes, sample_rate=sr, generation_id=gen)
        except Exception as e:
            self._log("warn", f"WAV çalma hatası ({wav_path}): {e}")
            return False

    def _flush_queue_locked(self) -> None:
        while not self._play_queue.empty():
            try:
                self._play_queue.get_nowait()
            except queue.Empty:
                break

    def _stop_active_processes_locked(self) -> None:
        if self._current_process is not None:
            try:
                self._current_process.terminate()
                self._current_process.wait(timeout=0.1)
            except Exception:
                try:
                    self._current_process.kill()
                except Exception:
                    pass
            self._current_process = None

    def _playback_loop(self) -> None:
        """Dedicated sounddevice OutputStream playback thread."""
        if sd is None:
            self._log("error", "❌ [AudioOutputManager] sounddevice bulunamadı!")
            return

        stream = None
        try:
            stream = sd.RawOutputStream(
                samplerate=HW_SAMPLE_RATE,
                blocksize=0,
                device=self.sd_dev_idx,
                channels=CHANNELS,
                dtype=DTYPE,
            )
            stream.start()
            self._output_stream = stream
        except Exception as e:
            self._log("warn", f"⚠️ [AudioOutputManager] Sounddevice OutputStream başlatılamadı: {e}. ALSA aplay fallback kullanılacak.")

        while True:
            try:
                gen, chunk = self._play_queue.get(timeout=0.1)
            except queue.Empty:
                if self._is_playing:
                    self._is_playing = False
                    if self._on_state_change:
                        self._on_state_change(False)
                continue

            with self._lock:
                if gen < self._current_generation:
                    continue  # Discard stale generation chunk
                self._is_playing = True
                self._last_playback_time = time.monotonic()

                # Trigger first audio timestamp callback
                if self._first_audio_emitted_for_gen != gen:
                    self._first_audio_emitted_for_gen = gen
                    if self._on_first_audio:
                        self._on_first_audio(gen, self._last_playback_time)
                    if self._on_state_change:
                        self._on_state_change(True)

            # Write chunk directly to hardware DAC
            if stream is not None and stream.active:
                try:
                    stream.write(chunk)
                except Exception as e:
                    self._log("debug", f"Audio stream write notice: {e}")
            else:
                # Fallback to direct aplay pipe
                self._play_chunk_via_aplay(chunk)

    def _play_chunk_via_aplay(self, chunk: bytes) -> None:
        try:
            cmd = ["aplay", "-D", self.alsa_device, "-r", "16000", "-f", "S16_LE", "-c", "1", "-q"]
            proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
            with self._lock:
                self._current_process = proc
            proc.communicate(input=chunk, timeout=2.0)
        except Exception:
            pass
        finally:
            with self._lock:
                self._current_process = None
