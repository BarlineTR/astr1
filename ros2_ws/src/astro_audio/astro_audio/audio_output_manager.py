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
from typing import Any, Callable, Dict, Optional, Tuple

import numpy as np

try:
    import sounddevice as sd
except ImportError:
    sd = None

RESPEAKER_NAME_HINTS = ("respeaker", "uac1", "seeed", "arrayuac", "usb audio")
# PulseAudio/PipeWire'ın ALSA köprüsü üzerinden açılan PortAudio çıkış akışları,
# başka bir süreç aynı sunucudan yakalama (capture) akışı tutarken Pa_WriteStream
# içinde kalıcı olarak kilitleniyor: ilk tampon duyuluyor, sonrası hiç akmıyor.
# Bu adlarda aplay alt sürecine düşülür; gerçek donanım (ReSpeaker vb.) için
# düşük gecikmeli doğrudan akış korunur.
PULSE_BRIDGE_NAMES = ("pulse", "pipewire", "default", "sysdefault", "jack")
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


def resolve_output_backend(preferred: str, sd_dev_name: str, sd_available: bool = True) -> str:
    """Seçilen çıkış cihazına göre 'sounddevice' mi 'aplay' mi kullanılacağına karar verir.

    sounddevice hiç kurulu değilse (ör. düğüm proje venv'i olmadan başlatıldıysa)
    PortAudio yolu tamamen kullanılamaz; bu durumda aplay tek seçenektir.
    """
    choice = (preferred or "auto").strip().lower()
    if choice == "aplay":
        return "aplay"
    if choice == "sounddevice" and sd_available:
        return "sounddevice"
    if not sd_available:
        return "aplay"
    name = (sd_dev_name or "").strip().lower()
    if any(name == n or name.startswith(n) for n in PULSE_BRIDGE_NAMES):
        return "aplay"
    return "sounddevice"


class AudioOutputManager:
    """Centralized, thread-safe hardware audio playback controller with generation gating."""

    def __init__(
        self,
        preferred_device: str = "",
        on_playback_state_change: Optional[Callable[[bool], None]] = None,
        on_first_audio_callback: Optional[Callable[[int, float], None]] = None,
        mock_playback: bool = False,
        logger: Optional[Callable[[str, str], None]] = None,
    ):
        self._log = logger or (lambda lvl, msg: None)
        self._on_state_change = on_playback_state_change
        self._on_first_audio = on_first_audio_callback
        self.mock_playback = mock_playback or (os.getenv("ASTRO_MOCK_AUDIO", "0") in ("1", "true", "True"))

        if not self.mock_playback:
            self.alsa_device = find_alsa_respeaker_device()
            self.sd_dev_idx, self.sd_dev_name = find_sounddevice_output_index(preferred_device)
            self.has_aplay = shutil.which("aplay") is not None
            self.backend = resolve_output_backend(
                os.getenv("AUDIO_OUTPUT_BACKEND", "auto"),
                self.sd_dev_name,
                sd_available=sd is not None,
            )
            if self.backend == "aplay" and not self.has_aplay:
                self.backend = "sounddevice"
            if self.backend == "sounddevice" and sd is None:
                self._log("error", "❌ [AudioOutputManager] Ne sounddevice ne aplay var — ses çıkışı yok!")
        else:
            self.alsa_device = "mock"
            self.sd_dev_idx, self.sd_dev_name = None, "Mock In-Memory Audio Device"
            self.has_aplay = False
            self.backend = "mock"

        self._play_queue: queue.Queue[Tuple[int, bytes]] = queue.Queue(maxsize=1000)
        self._current_generation = 0
        self._lock = threading.Lock()
        self._is_playing = False
        self._last_playback_time = 0.0
        self._first_audio_emitted_for_gen = -1
        self._played_bytes_for_gen: Dict[int, int] = {}

        self._current_process: Optional[subprocess.Popen] = None
        self._output_stream = None

        # Dedicated worker thread for sounddevice PCM streaming
        self._worker_thread = threading.Thread(target=self._playback_loop, daemon=True)
        self._worker_thread.start()

        mode_str = (
            "MOCK (In-Memory Isolation)" if self.mock_playback
            else f"Arka uç: [{self.backend}] | ALSA: [{self.alsa_device}] | Sounddevice: [{self.sd_dev_idx}: {self.sd_dev_name}]"
        )
        self._log("info", f"🔊 [AudioOutputManager] Başlatıldı | Mod: {mode_str}")

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

    def play_pcm_chunk(
        self,
        pcm_data: bytes,
        sample_rate: int = 16000,
        generation_id: Optional[int] = None,
        provenance: Optional[Dict[str, Any]] = None,
    ) -> bool:
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
            item = {
                "gen": gen,
                "pcm": raw_16k,
                "provenance": provenance or {},
                "raw_len": len(pcm_data),
            }
            self._play_queue.put_nowait(item)
            return True
        except queue.Full:
            self._log("warn", "⚠️ [AudioOutputManager] Çalma kuyruğu dolu, blok atlandı!")
            return False

    def play_wav_file(self, wav_path: str, generation_id: Optional[int] = None, blocking: bool = False, provenance: Optional[Dict[str, Any]] = None) -> bool:
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
                return self.play_pcm_chunk(raw_bytes, sample_rate=sr, generation_id=gen, provenance=provenance)
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
                if self._current_process.stdin:
                    try:
                        self._current_process.stdin.close()
                    except Exception:
                        pass
                self._current_process.terminate()
                self._current_process.wait(timeout=0.15)
            except Exception:
                try:
                    self._current_process.kill()
                except Exception:
                    pass
            self._current_process = None

    def _open_output_stream(self):
        """aplay arka ucunda akış açılmaz; aksi hâlde donanım DAC akışı açılır."""
        if self.backend == "aplay":
            self._log("info", f"🔈 [AudioOutputManager] Çalma aplay akışı ile yapılacak (cihaz: {self.alsa_device}).")
            return None
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
            return stream
        except Exception as e:
            self._log("warn", f"⚠️ [AudioOutputManager] Sounddevice OutputStream başlatılamadı: {e}. ALSA aplay fallback kullanılacak.")
            return None

    def _play_chunk_via_aplay_pipe(self, chunk: bytes, gen: int) -> bool:
        """Writes PCM chunk to an aplay subprocess, closes stdin to flush, and lets it play to completion."""
        with self._lock:
            if gen < self._current_generation:
                return False
            
            if self._current_process is None or self._current_process.poll() is not None:
                try:
                    cmd = ["aplay", "-D", self.alsa_device, "-r", str(HW_SAMPLE_RATE), "-f", "S16_LE", "-c", "1", "-q"]
                    self._current_process = subprocess.Popen(cmd, stdin=subprocess.PIPE)
                except Exception as e:
                    self._log("error", f"❌ [AudioOutputManager] alsa_write_error={e}")
                    self._current_process = None
                    return False

            proc = self._current_process

        import errno
        for attempt in range(3):
            try:
                if proc and proc.stdin:
                    proc.stdin.write(chunk)
                    proc.stdin.flush()
                    try:
                        proc.stdin.close()
                    except Exception:
                        pass
                    return True
            except OSError as e:
                if getattr(e, "errno", None) == errno.EINTR:
                    self._log("debug", f"⚡ [AudioOutputManager] alsa_write_retry_reason=EINTR (attempt {attempt+1}/3)")
                    time.sleep(0.01)
                    continue
                self._log("warn", f"⚠️ [AudioOutputManager] alsa_write_error={e}")
                with self._lock:
                    self._stop_active_processes_locked()
                return False
            except Exception as e:
                self._log("warn", f"⚠️ [AudioOutputManager] alsa_write_error={e}")
                with self._lock:
                    self._stop_active_processes_locked()
                return False
        return False

    def _playback_loop(self) -> None:
        """Dedicated playback thread (hardware DAC stream or streaming aplay subprocess)."""
        if self.mock_playback:
            while True:
                try:
                    raw_item = self._play_queue.get(timeout=0.05)
                except queue.Empty:
                    if self._is_playing:
                        with self._lock:
                            self._is_playing = False
                            finished_gen = self._first_audio_emitted_for_gen
                            total_played = self._played_bytes_for_gen.get(finished_gen, 0)
                        if finished_gen >= 0:
                            self._log(
                                "info",
                                f"🔊 [PLAYBACK FINISHED]\n"
                                f"  generation_id={finished_gen}\n"
                                f"  playback_started=true\n"
                                f"  playback_finished=true\n"
                                f"  playback_failed=false\n"
                                f"  played_bytes={total_played}\n"
                                f"  device={self.alsa_device}"
                            )
                        if self._on_state_change:
                            self._on_state_change(False)
                    continue

                if isinstance(raw_item, tuple):
                    gen, chunk = raw_item[0], raw_item[1]
                    prov = {}
                else:
                    gen, chunk = raw_item["gen"], raw_item["pcm"]
                    prov = raw_item.get("provenance", {})

                with self._lock:
                    if gen < self._current_generation:
                        continue
                    self._is_playing = True
                    self._last_playback_time = time.monotonic()
                    self._played_bytes_for_gen[gen] = self._played_bytes_for_gen.get(gen, 0) + len(chunk)
                    if self._first_audio_emitted_for_gen != gen:
                        self._first_audio_emitted_for_gen = gen
                        self._log(
                            "info",
                            f"🔊 [PLAYBACK STARTED]\n"
                            f"  generation_id={gen}\n"
                            f"  playback_started=true\n"
                            f"  playback_finished=false\n"
                            f"  playback_failed=false\n"
                            f"  tts_provider={prov.get('tts_provider', 'mock')}\n"
                            f"  tts_source={prov.get('tts_source', 'mock')}\n"
                            f"  playback_source={prov.get('playback_source', self.backend)}\n"
                            f"  played_bytes={len(chunk)}\n"
                            f"  device={self.alsa_device}"
                        )
                        if self._on_first_audio:
                            self._on_first_audio(gen, self._last_playback_time)
                        if self._on_state_change:
                            self._on_state_change(True)
            return

        if sd is None and self.backend != "aplay":
            self._log("error", "❌ [AudioOutputManager] sounddevice bulunamadı!")
            return

        stream = self._open_output_stream()

        while True:
            # Check if active process is still playing before resetting state
            if self._current_process is not None:
                if self._current_process.poll() is None:
                    # aplay is still playing through hardware DAC
                    try:
                        raw_item = self._play_queue.get(timeout=0.05)
                    except queue.Empty:
                        continue
                else:
                    self._current_process = None

            try:
                raw_item = self._play_queue.get(timeout=0.05)
            except queue.Empty:
                if self._current_process is not None and self._current_process.poll() is None:
                    continue
                if self._is_playing:
                    with self._lock:
                        self._is_playing = False
                        finished_gen = self._first_audio_emitted_for_gen
                        total_played = self._played_bytes_for_gen.get(finished_gen, 0)
                    if finished_gen >= 0:
                        self._log(
                            "info",
                            f"🔊 [PLAYBACK FINISHED]\n"
                            f"  generation_id={finished_gen}\n"
                            f"  playback_started=true\n"
                            f"  playback_finished=true\n"
                            f"  playback_failed=false\n"
                            f"  played_bytes={total_played}\n"
                            f"  device={self.alsa_device}"
                        )
                    if self._on_state_change:
                        self._on_state_change(False)
                continue

            if isinstance(raw_item, tuple):
                gen, chunk = raw_item[0], raw_item[1]
                prov = {}
            else:
                gen, chunk = raw_item["gen"], raw_item["pcm"]
                prov = raw_item.get("provenance", {})

            with self._lock:
                if gen < self._current_generation:
                    self._stop_active_processes_locked()
                    continue  # Discard stale generation chunk
                self._is_playing = True
                self._last_playback_time = time.monotonic()
                self._played_bytes_for_gen[gen] = self._played_bytes_for_gen.get(gen, 0) + len(chunk)

                # Trigger first audio timestamp callback & provenance logging
                if self._first_audio_emitted_for_gen != gen:
                    self._first_audio_emitted_for_gen = gen
                    self._log(
                        "info",
                        f"🔊 [PLAYBACK STARTED]\n"
                        f"  generation_id={gen}\n"
                        f"  playback_started=true\n"
                        f"  playback_finished=false\n"
                        f"  playback_failed=false\n"
                        f"  tts_provider={prov.get('tts_provider', 'edge_tts')}\n"
                        f"  tts_model={prov.get('tts_model', 'edge_neural')}\n"
                        f"  tts_source={prov.get('tts_source', 'cloud')}\n"
                        f"  playback_source={prov.get('playback_source', self.backend)}\n"
                        f"  played_bytes={len(chunk)}\n"
                        f"  device={self.alsa_device}"
                    )
                    if self._on_first_audio:
                        self._on_first_audio(gen, self._last_playback_time)
                    if self._on_state_change:
                        self._on_state_change(True)

            # Write chunk directly to hardware DAC or streaming aplay pipe
            if stream is not None and stream.active:
                try:
                    stream.write(chunk)
                except Exception as e:
                    self._log("warn", f"⚠️ [AudioOutputManager] alsa_write_error={e}")
            else:
                self._play_chunk_via_aplay_pipe(chunk, gen)
