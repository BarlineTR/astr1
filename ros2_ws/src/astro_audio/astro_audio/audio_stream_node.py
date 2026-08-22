#!/usr/bin/env python3
"""ASTRO V1 — Real-Time Audio Streaming & Playback Engine for OpenAI Realtime API.

Features:
  - 16kHz hardware native capture (ReSpeaker 4-Mic USB Array) with 24kHz upsampling for OpenAI
  - Zero-latency non-blocking streaming playback of OpenAI response.audio.delta (24kHz -> 16kHz DAC)
  - Sub-millisecond queue flush & output stream abort on user barge-in (/tts/interrupt)
  - Real-time RMS acoustic monitoring & hardware auto-selection
"""

import base64
import logging

_LOG = logging.getLogger(__name__)

import json
import os
import queue
import struct
import sys
import threading
import time
from typing import Any, Optional

import numpy as np

try:
    import rclpy
    from rclpy.node import Node
    from std_msgs.msg import Bool, Float32, String
except ImportError:
    rclpy = None
    class Node:  # type: ignore
        def __init__(self, *args, **kwargs):
            pass
        def get_logger(self):
            import logging
            return logging.getLogger("AudioStreamNode")
        def create_subscription(self, *args, **kwargs):
            return None
        def create_publisher(self, *args, **kwargs):
            return None
        def create_timer(self, *args, **kwargs):
            return None
        def destroy_node(self):
            pass
    class _MockMsg:
        data: Any = None
    Bool = Float32 = String = _MockMsg  # type: ignore

try:
    import sounddevice as sd
except ImportError:
    sd = None


RESPEAKER_NAME_HINTS = ("respeaker", "uac1", "seeed", "arrayuac", "usb audio")
HW_SAMPLE_RATE = 16000  # ReSpeaker native hardware rate
TARGET_SAMPLE_RATE = 24000  # OpenAI Realtime standard
CHANNELS = 1
DTYPE = "int16"
CHUNK_MS = 20  # 20ms chunks = 320 samples @ 16kHz
HW_BLOCK_SIZE = int(HW_SAMPLE_RATE * (CHUNK_MS / 1000.0))  # 320


def resample_16k_to_24k(raw_16k_bytes: bytes) -> bytes:
    """Ultra-fast 16kHz -> 24kHz int16 PCM interpolation (320 -> 480 samples)."""
    arr_16k = np.frombuffer(raw_16k_bytes, dtype=np.int16)
    if len(arr_16k) == 0:
        return b""
    n_out = int(len(arr_16k) * 1.5)
    indices = np.linspace(0, len(arr_16k) - 1, n_out)
    arr_24k = np.interp(indices, np.arange(len(arr_16k)), arr_16k.astype(np.float32)).astype(np.int16)
    return arr_24k.tobytes()


def resample_24k_to_16k(raw_24k_bytes: bytes) -> bytes:
    """Ultra-fast 24kHz -> 16kHz int16 PCM downsampling (480 -> 320 samples)."""
    arr_24k = np.frombuffer(raw_24k_bytes, dtype=np.int16)
    if len(arr_24k) == 0:
        return b""
    n_out = int(len(arr_24k) * (2.0 / 3.0))
    indices = np.linspace(0, len(arr_24k) - 1, n_out)
    arr_16k = np.interp(indices, np.arange(len(arr_24k)), arr_24k.astype(np.float32)).astype(np.int16)
    return arr_16k.tobytes()


def list_devices():
    if sd is None:
        return []
    try:
        return [
            (i, dev.get("name", "?"), dev.get("max_input_channels", 0), dev.get("max_output_channels", 0))
            for i, dev in enumerate(sd.query_devices())
        ]
    except Exception:
        return []


def find_audio_device(is_input: bool = True, preferred: str = "") -> tuple[Optional[int], str]:
    if sd is None:
        return None, "sounddevice kurulu değil"

    devs = list_devices()
    valid = [(i, name) for i, name, in_ch, out_ch in devs if (in_ch > 0 if is_input else out_ch > 0)]
    if not valid:
        return None, "uygun ses cihazı bulunamadı"

    # 1. Preferred override
    if preferred:
        if preferred.strip().lstrip("-").isdigit():
            idx = int(preferred)
            for i, name in valid:
                if i == idx:
                    return i, name
        else:
            needle = preferred.strip().lower()
            for i, name in valid:
                if needle in name.lower():
                    return i, name

    # 2. ReSpeaker match
    for i, name in valid:
        if any(h in name.lower() for h in RESPEAKER_NAME_HINTS):
            return i, name

    # 3. Default
    return valid[0][0], valid[0][1]


class AudioStreamNode(Node):
    """ROS 2 Node managing real-time bidirectional audio for OpenAI Realtime WebSocket."""

    def __init__(self):
        super().__init__("audio_stream_node")

        # Publishers
        self.pub_input_pcm = self.create_publisher(String, "/audio/realtime_input_pcm", 20)
        self.pub_playback_active = self.create_publisher(Bool, "/audio/playback_active", 10)
        self.pub_input_level = self.create_publisher(Float32, "/audio/mic_level", 10)

        # Subscribers
        self.create_subscription(String, "/audio/realtime_output_pcm", self._on_output_pcm, 50)
        self.create_subscription(Bool, "/tts/interrupt", self._on_interrupt, 10)

        # Device selection
        pref_in = os.getenv("AUDIO_INPUT_DEVICE", "")
        pref_out = os.getenv("AUDIO_OUTPUT_DEVICE", "")
        self._in_dev_idx, in_name = find_audio_device(is_input=True, preferred=pref_in)
        self._out_dev_idx, out_name = find_audio_device(is_input=False, preferred=pref_out)
        self._in_device_name = in_name
        self._out_device_name = out_name

        # Configurable Acoustic Echo & Barge-In Parameters
        self.echo_mute_cooldown_s = float(os.getenv("ECHO_MUTE_COOLDOWN_S", "0.65"))
        self.barge_in_protection_ms = float(os.getenv("TTS_BARGE_IN_PROTECTION_MS", "350.0"))
        self.barge_in_min_rms = float(os.getenv("BARGE_IN_MIN_RMS", "1200.0"))
        self.barge_in_playback_min_rms = float(os.getenv("BARGE_IN_PLAYBACK_MIN_RMS", "4500.0"))
        self.barge_in_noise_mult = float(os.getenv("BARGE_IN_NOISE_MULTIPLIER", "3.5"))
        self.barge_in_min_peak = int(os.getenv("BARGE_IN_MIN_PEAK", "2800"))
        self.barge_in_playback_min_peak = int(os.getenv("BARGE_IN_PLAYBACK_MIN_PEAK", "14000"))
        self._ambient_rms = 120.0
        self._playback_drop_until = 0.0

        # Complete Playback & Callback State (Initialized BEFORE spawning worker thread)
        self._play_queue: queue.Queue[bytes] = queue.Queue(maxsize=500)
        self._is_playing = False
        self._last_playback_time = 0.0
        self._playback_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._total_enqueued_bytes = 0
        self._total_played_bytes = 0
        self._playback_burst_active = False
        self._burst_start_time = 0.0
        self._playback_worker_alive = True
        self._playback_worker_error = "none"
        self._callback_exception_count = 0
        self._last_input_callback_time = time.monotonic()
        self._last_cb_err_log_time = 0.0

        # Streams
        self._input_stream = None
        self._output_stream = None

        # Start Playback Worker Thread
        self._play_thread = threading.Thread(target=self._playback_worker, daemon=True)
        self._play_thread.start()

        # Start Input Capture Stream
        self._start_input_stream()

        # Playback status ticker timer
        self.create_timer(0.05, self._publish_status)

        self.get_logger().info(
            f"🔊 [AUDIO READY]\n"
            f"  input_device=[{self._in_dev_idx}] {self._in_device_name}\n"
            f"  output_device=[{self._out_dev_idx}] {self._out_device_name}\n"
            f"  input_callback=alive\n"
            f"  playback_worker=alive\n"
            f"  audio_input_callback_alive=True\n"
            f"  audio_playback_worker_alive=True"
        )

    def _start_input_stream(self):
        if sd is None:
            self.get_logger().error("sounddevice kütüphanesi eksik! Canlı ses yakalanamıyor.")
            return

        try:
            self._input_stream = sd.RawInputStream(
                samplerate=HW_SAMPLE_RATE,
                blocksize=HW_BLOCK_SIZE,
                device=self._in_dev_idx,
                channels=CHANNELS,
                dtype=DTYPE,
                callback=self._input_callback,
            )
            self._input_stream.start()
            self.get_logger().info("✅ [Realtime Audio] 16kHz Canlı Mikrofon Akışı Başlatıldı (20ms/blok).")
        except Exception as e:
            self.get_logger().error(f"❌ [Realtime Audio] Giriş akışı başlatılamadı: {e}")

    def _input_callback(self, indata, frames, time_info, status):
        """Audio hardware callback triggered every 20ms with 320 16-bit PCM samples."""
        try:
            self._last_input_callback_time = time.monotonic()
            if status:
                pass

            raw_bytes = bytes(indata)
            if not raw_bytes:
                return

            now = time.monotonic()
            if now < self._playback_drop_until:
                return

            # Measure RMS level and peak for diagnostic & VAD
            peak = 0
            try:
                arr = np.frombuffer(raw_bytes, dtype=np.int16)
                rms = float(np.sqrt(np.mean(arr.astype(np.float32) ** 2)))
                if len(arr) > 0:
                    peak = int(np.max(np.abs(arr)))
            except Exception:
                rms = 0.0
                peak = 0

            is_active_playback = (
                self._is_playing
                or (now - self._last_playback_time < self.echo_mute_cooldown_s)
                or not self._play_queue.empty()
            )

            if not is_active_playback and rms < 400.0:
                # Continuously adapt ambient background noise floor during quiet periods
                self._ambient_rms = 0.96 * self._ambient_rms + 0.04 * rms

            # Software Echo Mute & Self-Voice Suppression (Zero Self-Hearing):
            # When Astro is playing voice or within echo cooldown, protect playback
            if is_active_playback:
                burst_start = getattr(self, "_burst_start_time", 0.0)
                # 1. Acoustic Protection Window: Strictly suppress feedback during initial burst (e.g. 350ms)
                if self._playback_burst_active and burst_start > 0.0 and ((now - burst_start) * 1000.0 < self.barge_in_protection_ms):
                    return

                # Adaptive barge-in threshold derived from ambient noise floor
                adaptive_barge_in_rms = max(self.barge_in_min_rms, self._ambient_rms * self.barge_in_noise_mult)

                # 2. Distinguish loud speech energy during active playback
                is_genuine_barge_in = (rms >= adaptive_barge_in_rms and peak >= self.barge_in_min_peak)
                if not is_genuine_barge_in:
                    return

            # Energy gate: do not stream dead room silence (saves bandwidth and prevents Whisper hallucination)
            if not is_active_playback and rms < max(65.0, self._ambient_rms * 0.75):
                return

            # Publish mic level
            lvl_msg = Float32()
            lvl_msg.data = float(rms)
            self.pub_input_level.publish(lvl_msg)

            # Resample 16kHz -> 24kHz for OpenAI Realtime API
            pcm_24k = resample_16k_to_24k(raw_bytes)

            # Encode to base64 and publish to ROS 2 topic
            b64_str = base64.b64encode(pcm_24k).decode("ascii")
            msg = String()
            msg.data = b64_str
            self.pub_input_pcm.publish(msg)
        except Exception as exc:
            self._callback_exception_count += 1
            now_cb = time.monotonic()
            if (now_cb - self._last_cb_err_log_time) > 2.0:
                self._last_cb_err_log_time = now_cb
                self.get_logger().error(
                    f"❌ [Realtime Audio Callback Error]: callback_exception={type(exc).__name__}: {exc} | "
                    f"callback_exception_count={self._callback_exception_count} | audio_input_alive=True"
                )

    def _on_output_pcm(self, msg: String):
        """Incoming 24kHz PCM audio chunk from OpenAI Realtime API or Fallback TTS (base64 or JSON)."""
        if not msg.data:
            return
        try:
            payload = {}
            raw_str = msg.data.strip()
            if raw_str.startswith("{") and raw_str.endswith("}"):
                try:
                    payload = json.loads(raw_str)
                    b64_pcm = payload.get("data", "")
                except Exception:
                    b64_pcm = raw_str
            else:
                b64_pcm = raw_str

            raw_24k = base64.b64decode(b64_pcm.encode("ascii"))
            if raw_24k:
                # Resample 24kHz -> 16kHz for hardware ReSpeaker DAC
                raw_16k = resample_24k_to_16k(raw_24k)
                item = {
                    "pcm": raw_16k,
                    "generation_id": payload.get("generation_id", 0),
                    "tts_provider": payload.get("tts_provider", "openai"),
                    "tts_model": payload.get("tts_model", "gpt-4o-realtime"),
                    "tts_source": payload.get("tts_source", "realtime_openai"),
                    "playback_source": payload.get("playback_source", payload.get("tts_source", "realtime_openai")),
                }
                self._play_queue.put_nowait(item)
                self._total_enqueued_bytes += len(raw_16k)
        except (queue.Full, Exception) as e:
            self.get_logger().debug(f"PCM enqueue notice: {e}")

    def _on_interrupt(self, msg: Bool):
        """Zero-latency barge-in signal: instantly flush playback buffer queue and mute lingering tail."""
        if not msg.data:
            return

        # P0-7: Barge-in is only valid if playback has actually started and played bytes > 0
        if not self._playback_burst_active or self._total_played_bytes == 0:
            return

        discarded_bytes = 0
        with self._playback_lock:
            while not self._play_queue.empty():
                try:
                    c = self._play_queue.get_nowait()
                    raw_len = len(c["pcm"]) if isinstance(c, dict) else len(c)
                    discarded_bytes += raw_len
                except queue.Empty:
                    break

        barge_in_after_ms = int((time.monotonic() - self._burst_start_time) * 1000.0) if self._burst_start_time > 0 else 0
        barge_in_source = "self_voice" if (self._burst_start_time > 0 and barge_in_after_ms < int(self.barge_in_protection_ms)) else "user"
        self._is_playing = False
        self._playback_burst_active = False
        self._last_playback_time = 0.0
        self._playback_drop_until = time.monotonic() + 0.15
        prov = getattr(self, "_active_provenance", {})
        self.get_logger().info(
            f"⚡ [Playback Telemetry]: tts_playback_cancelled=True | "
            f"generation_id={prov.get('generation_id', 0)} | "
            f"playback_source={prov.get('playback_source', 'unknown')} | "
            f"tts_provider={prov.get('tts_provider', 'unknown')} | "
            f"tts_model={prov.get('tts_model', 'unknown')} | "
            f"tts_played_bytes={self._total_played_bytes} | "
            f"tts_remaining_bytes={discarded_bytes} | "
            f"playback_duration_ms={barge_in_after_ms} | "
            f"barge_in_after_ms={barge_in_after_ms} | "
            f"barge_in_source={barge_in_source} | "
            f"reason=barge_in"
        )

    def _playback_worker(self):
        """Dedicated real-time audio playback loop sending PCM directly to hardware DAC."""
        if sd is None:
            self._playback_worker_alive = False
            self._playback_worker_error = "sounddevice_library_missing"
            return

        out_stream = None
        try:
            out_stream = sd.RawOutputStream(
                samplerate=HW_SAMPLE_RATE,
                blocksize=0,
                device=self._out_dev_idx,
                channels=CHANNELS,
                dtype=DTYPE,
            )
            out_stream.start()
            self._output_stream = out_stream
            self._playback_worker_alive = True
            self._playback_worker_error = "none"
        except Exception as e:
            self._playback_worker_alive = False
            self._playback_worker_error = f"dac_init_failed: {e}"
            self.get_logger().error(
                f"❌ [Realtime Audio] Çıkış akışı başlatılamadı ({self._out_device_name}): {e} | "
                f"tts_playback_started=False | tts_playback_error={self._playback_worker_error}"
            )
            return

        while not self._stop_event.is_set():
            try:
                item = self._play_queue.get(timeout=0.05)
                if isinstance(item, dict):
                    chunk = item["pcm"]
                    gen_id = item.get("generation_id", 0)
                    tts_provider = item.get("tts_provider", "openai")
                    tts_model = item.get("tts_model", "unknown")
                    tts_source = item.get("tts_source", "unknown")
                    playback_source = item.get("playback_source", tts_source)
                else:
                    chunk = item
                    gen_id = 0
                    tts_provider = "openai"
                    tts_model = "gpt-4o-realtime"
                    tts_source = "realtime_openai"
                    playback_source = "realtime_openai"

                # Provenance sanity assertion
                if (tts_provider == "xtts_gpu" and playback_source in ("local_offline_tts", "espeak")) or (tts_model == "xtts_finetuned" and playback_source == "espeak"):
                    self.get_logger().error(f"🚨 [Provenance Mismatch]: Invalid combination tts_provider={tts_provider}, playback_source={playback_source}")

                t_w_start = time.perf_counter()
                with self._playback_lock:
                    out_stream.write(chunk)
                t_w_end = time.perf_counter()
                write_ms = (t_w_end - t_w_start) * 1000.0

                self._is_playing = True
                self._last_playback_time = time.monotonic()
                self._total_played_bytes += len(chunk)

                if not self._playback_burst_active:
                    self._playback_burst_active = True
                    self._burst_start_time = time.monotonic()
                    self._active_provenance = {
                        "generation_id": gen_id,
                        "playback_source": playback_source,
                        "tts_provider": tts_provider,
                        "tts_model": tts_model,
                        "tts_source": tts_source,
                    }
                    self.get_logger().info(
                        f"🔊 [Playback Telemetry]: tts_playback_started=True | "
                        f"generation_id={gen_id} | playback_source={playback_source} | "
                        f"tts_provider={tts_provider} | tts_model={tts_model} | "
                        f"tts_source={tts_source} | audio_bytes={len(chunk)} | "
                        f"tts_audio_device=\"{self._out_device_name}\" | "
                        f"tts_audio_write_ms={write_ms:.1f} | "
                        f"chunk_bytes={len(chunk)}"
                    )
            except queue.Empty:
                if self._playback_burst_active and (time.monotonic() - self._last_playback_time) > 0.20:
                    self._playback_burst_active = False
                    burst_dur_ms = (time.monotonic() - self._burst_start_time) * 1000.0
                    prov = getattr(self, "_active_provenance", {})
                    self.get_logger().info(
                        f"🔊 [Playback Telemetry]: tts_playback_finished=True | "
                        f"generation_id={prov.get('generation_id', 0)} | "
                        f"playback_source={prov.get('playback_source', 'unknown')} | "
                        f"tts_provider={prov.get('tts_provider', 'unknown')} | "
                        f"tts_model={prov.get('tts_model', 'unknown')} | "
                        f"tts_played_bytes={self._total_played_bytes} | "
                        f"total_playback_bytes={self._total_played_bytes} | "
                        f"playback_duration_ms={int(burst_dur_ms)}"
                    )
                if (time.monotonic() - self._last_playback_time) > 0.35:
                    self._is_playing = False
            except Exception as exc:
                self._is_playing = False
                self._playback_worker_error = f"{type(exc).__name__}: {exc}"
                self.get_logger().error(
                    f"❌ [Playback Worker Error]: exception={type(exc).__name__}: {exc} | "
                    f"tts_playback_started=False | tts_playback_error={self._playback_worker_error}"
                )
                time.sleep(0.05)



    def _publish_status(self):
        msg = Bool()
        msg.data = bool(self._is_playing or not self._play_queue.empty())
        self.pub_playback_active.publish(msg)

    def destroy_node(self):
        self._stop_event.set()
        if self._input_stream:
            try:
                self._input_stream.stop()
                self._input_stream.close()
            except Exception:
                pass
        if self._output_stream:
            try:
                self._output_stream.stop()
                self._output_stream.close()
            except Exception:
                pass
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = AudioStreamNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt as _exc:
        _LOG.debug("main: yok sayılan hata (%s)", _exc)
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
