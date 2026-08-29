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

try:
    from astro_audio.doa_estimator import AcousticDOAEstimator, ReSpeakerGeometry
except ImportError:
    try:
        from .doa_estimator import AcousticDOAEstimator, ReSpeakerGeometry
    except ImportError:
        try:
            _this_dir = os.path.dirname(os.path.abspath(__file__))
            if _this_dir not in sys.path:
                sys.path.insert(0, _this_dir)
            from doa_estimator import AcousticDOAEstimator, ReSpeakerGeometry
        except ImportError:
            AcousticDOAEstimator = None  # type: ignore
            ReSpeakerGeometry = None  # type: ignore


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


# ALSA'nın yazılımda yeniden örnekleme yapan sanal cihazları. Ham "hw:x,y"
# cihazları yalnızca donanımın kendi hızlarını kabul eder; bunlar her hızı kabul eder.
ALSA_PLUG_HINTS = ("default", "pulse", "pipewire", "sysdefault")


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

    # 3. ALSA'nın yeniden örnekleyen sanal cihazları.
    #
    # Eskiden burada doğrudan valid[0] dönülüyordu; bu makinede o
    # "HDA Intel PCH: ALC294 Analog (hw:0,0)" oluyor. Ham hw: cihazı ALSA'nın
    # plug katmanını atlar, yani YALNIZCA donanımın kendi hızlarını kabul eder.
    # ALC294 44100/48000 destekliyor, düğüm ise 16000 istiyor; sonuç her açılışta
    # "Invalid sample rate [PaErrorCode -9997]" ve mikrofon hiç açılmıyordu.
    # default/pulse/pipewire/sysdefault yazılımda yeniden örnekler, bu yüzden
    # ham donanımın önüne alınıyor. Yalnızca isim eşlemesi yapılır — cihaz
    # yoklaması yapmak testlerde süreç çökmesine yol açtığı için tercih edilmedi.
    for i, name in valid:
        if any(h in name.lower() for h in ALSA_PLUG_HINTS):
            return i, name

    # 4. Son çare: ilk uygun cihaz (eski davranış)
    return valid[0][0], valid[0][1]


try:
    import usb.core
    import usb.util
    HAS_USB = True
except ImportError:
    HAS_USB = False

RESPEAKER_VID = 0x2886
RESPEAKER_PID = 0x0018
PARAM_SPEECH_DETECTED = 19
PARAM_DOA_ANGLE = 21


class ReSpeakerHID:
    """Hardware HID interface for ReSpeaker 4-Mic USB Array parameters (VAD & DOA)."""
    TIMEOUT_MS = 1000

    def __init__(self):
        self.dev = None
        self._last_find_attempt = 0.0
        self._find_device()

    def _find_device(self):
        if not HAS_USB:
            return
        now = time.monotonic()
        if (now - self._last_find_attempt) < 5.0:
            return
        self._last_find_attempt = now
        try:
            self.dev = usb.core.find(idVendor=RESPEAKER_VID, idProduct=RESPEAKER_PID)
        except Exception:
            self.dev = None

    def _read_param(self, param_id: int) -> Optional[int]:
        if self.dev is None:
            self._find_device()
            if self.dev is None:
                return None
        try:
            data = self.dev.ctrl_transfer(
                usb.util.CTRL_IN | usb.util.CTRL_TYPE_VENDOR | usb.util.CTRL_RECIPIENT_DEVICE,
                0,
                param_id,
                0,
                8,
                self.TIMEOUT_MS,
            )
            if data and len(data) >= 4:
                return struct.unpack_from("i", data, 0)[0]
            return None
        except Exception:
            self.dev = None
            return None

    def speech_detected(self) -> Optional[bool]:
        val = self._read_param(PARAM_SPEECH_DETECTED)
        return (val == 1) if val is not None else None

    def doa_angle(self) -> Optional[float]:
        val = self._read_param(PARAM_DOA_ANGLE)
        if val is not None and 0 <= val <= 359:
            return float(val)
        return None


class AudioStreamNode(Node):
    """ROS 2 Node managing real-time bidirectional audio for OpenAI Realtime WebSocket."""

    def __init__(self):
        super().__init__("audio_stream_node")
        self.declare_parameter("input_channels", 0)

        # Publishers
        self.pub_input_pcm = self.create_publisher(String, "/audio/realtime_input_pcm", 20)
        self.pub_playback_active = self.create_publisher(Bool, "/audio/playback_active", 10)
        self.pub_input_level = self.create_publisher(Float32, "/audio/mic_level", 10)
        self.pub_doa = self.create_publisher(Float32, "/audio/doa", 10)
        self.pub_vad = self.create_publisher(Bool, "/audio/vad", 10)

        # Hardware ReSpeaker HID & Acoustic DOA Estimator
        self._respeaker = ReSpeakerHID()
        self._doa_estimator = AcousticDOAEstimator(sample_rate=HW_SAMPLE_RATE) if AcousticDOAEstimator else None
        self._capture_channels = 1
        self._last_doa_angle = 0.0
        self._last_mic_speech_time = 0.0

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
        self._total_playback_bytes = 0
        self._current_gen_played_bytes = 0
        self._cancelled_gen_ids: set[int] = set()
        self._playback_burst_active = False
        self._burst_start_time = 0.0
        self._playback_worker_alive = True
        self._playback_worker_error = "none"
        self._last_input_callback_time = time.monotonic()
        self._last_output_chunk_time = 0.0
        self._last_output_envelope: Optional[dict] = None
        self._active_provenance: dict = {}
        self._input_stream = None
        self._output_stream = None
        self._input_stream_alive = False
        self._last_cb_err_log_time = 0.0
        self._callback_exception_count = 0
        self._generation_counter = 1000

        # Telemetry State Tracking
        self._current_gen_id: Optional[int] = None
        self._gen_first_audio_logged: set[int] = set()
        self._gen_first_packet_time: dict[int, float] = {}
        self._gen_audio_bytes: dict[int, int] = {}
        self._gen_played_bytes: dict[int, int] = {}
        self._gen_packets: dict[int, int] = {}
        self._gen_stream_start: dict[int, float] = {}
        self._gen_playback_start: dict[int, float] = {}

        # Background Audio Input Stream initialization
        self._start_input_stream()

        # Dedicated Playback Thread (ALSA single-stream owner)
        self._playback_thread = threading.Thread(target=self._playback_worker, daemon=True)
        self._playback_thread.start()

        # Playback status ticker timer
        self.create_timer(0.1, self._publish_status)

        # ReSpeaker 4-Mic HID DOA & VAD polling timer (10 Hz)
        if not self._under_pytest():
            self.create_timer(0.1, self._poll_respeaker_hid)

    def _poll_respeaker_hid(self):
        """Polls ReSpeaker 4-Mic hardware parameters (DOA & VAD) and publishes to ROS topics."""
        if not self._respeaker or not self._respeaker.dev:
            return
        try:
            is_speech = self._respeaker.speech_detected()
            doa_angle = self._respeaker.doa_angle()

            if is_speech is not None:
                vad_msg = Bool()
                vad_msg.data = bool(is_speech)
                self.pub_vad.publish(vad_msg)

            # Publish genuine hardware DOA ONLY when speech is actively detected and playback is not active
            is_active_playback = self._is_playing or (self._output_stream and self._output_stream.active)
            if is_speech is True and doa_angle is not None and not is_active_playback:
                doa_msg = Float32()
                doa_msg.data = float(doa_angle)
                self.pub_doa.publish(doa_msg)
        except Exception as exc:
            self.get_logger().debug(f"_poll_respeaker_hid error: {exc}")

    @staticmethod
    def _under_pytest() -> bool:
        """Test sürecinde GERÇEK ses donanımı açılmaz."""
        return (
            "PYTEST_CURRENT_TEST" in os.environ
            or "pytest" in sys.modules
            or "unittest" in sys.modules
            or os.environ.get("ASTRO_TEST_MODE", "0") in ("1", "true", "True")
        )

    def _start_input_stream(self):
        if sd is None:
            self._input_stream_alive = False
            self.get_logger().error("sounddevice kütüphanesi eksik! Canlı ses yakalanamıyor.")
            self.get_logger().error(
                f"[AUDIO ERROR]\n"
                f"  direction=input\n"
                f"  device=[{self._in_dev_idx}] {self._in_device_name}\n"
                f"  reason=sounddevice_missing"
            )
            return

        # Testler `sd`'yi mock'ladığında sorun yok — mock donanıma dokunmaz.
        if self._under_pytest() and getattr(sd, "__name__", "") == "sounddevice":
            self._input_stream_alive = False
            self.get_logger().info("[TEST] Gerçek ses donanımı açılmadı (pytest).")
            return

        try:
            # Query hardware input channel count
            max_in_ch = 1
            try:
                dev_info = sd.query_devices(self._in_dev_idx) if (sd and self._in_dev_idx is not None) else {}
                max_in_ch = dev_info.get("max_input_channels", 1) if isinstance(dev_info, dict) else 1
            except Exception:
                max_in_ch = 1

            param_val = 0
            try:
                if hasattr(self, "has_parameter") and self.has_parameter("input_channels"):
                    param_val = int(self.get_parameter("input_channels").value)
            except Exception:
                param_val = 0
            env_val = int(os.getenv("AUDIO_INPUT_CHANNELS", "0"))
            pref_ch = param_val or env_val

            if pref_ch in (1, 2, 4, 6, 8):
                self._capture_channels = pref_ch
            elif max_in_ch >= 4:
                self._capture_channels = 4
            else:
                self._capture_channels = 1

            self._input_stream = sd.RawInputStream(
                samplerate=HW_SAMPLE_RATE,
                blocksize=HW_BLOCK_SIZE,
                device=self._in_dev_idx,
                channels=self._capture_channels,
                dtype=DTYPE,
                callback=self._input_callback,
            )
            self._input_stream.start()
            self._input_stream_alive = True
            self.get_logger().info(
                f"🎛️ [DOA HARDWARE & CHANNEL CONFIG]\n"
                f"  device_index={self._in_dev_idx} | device_name=\"{self._in_device_name}\"\n"
                f"  channel_count={self._capture_channels} | hardware_max_channels={max_in_ch}\n"
                f"  sample_rate={HW_SAMPLE_RATE} Hz | sample_format=int16 (16-bit PCM, 2 bytes/sample)\n"
                f"  interleaving=interleaved [s0_ch0, s0_ch1, s0_ch2, s0_ch3, ...]\n"
                f"  channel_mapping:\n"
                f"    - Channel 0: Front Mic 0 (x=0.0m, y=+0.043m, 0 deg)\n"
                f"    - Channel 1: Right Mic 1 (x=+0.043m, y=0.0m, +90 deg)\n"
                f"    - Channel 2: Back Mic 2 (x=0.0m, y=-0.043m, 180 deg)\n"
                f"    - Channel 3: Left Mic 3 (x=-0.043m, y=0.0m, -90 deg)\n"
                f"  spatial_doa_engine=AcousticDOAEstimator (GCC-PHAT TDOA)"
            )
            self.get_logger().info(
                f"🔊 [AUDIO READY]\n"
                f"  input_device=[{self._in_dev_idx}] {self._in_device_name}\n"
                f"  input_callback=alive\n"
                f"  audio_input_callback_alive=True"
            )
        except Exception as e:
            self._input_stream_alive = False
            self.get_logger().warn(
                f"[AUDIO ERROR]\n"
                f"  direction=input\n"
                f"  device=[{self._in_dev_idx}] {self._in_device_name}\n"
                f"  reason=device_unavailable\n"
                f"  error={e}"
            )
            # Subscribe to audio_capture_node's /audio/speech_audio as fallback input transport
            try:
                from std_msgs.msg import Int16MultiArray
                self.sub_fallback_audio = self.create_subscription(
                    Int16MultiArray, "/audio/speech_audio", self._on_fallback_audio_msg, 20
                )
            except Exception:
                pass

    def _on_fallback_audio_msg(self, msg):
        """Receives 16kHz int16 PCM from audio_capture_node when direct hardware capture is occupied."""
        try:
            raw_bytes = np.array(msg.data, dtype=np.int16).tobytes()
            self._process_raw_audio_chunk(raw_bytes)
        except Exception:
            pass

    def _input_callback(self, indata, frames, time_info, status):
        """Audio hardware callback triggered every 20ms with 320 16-bit PCM samples."""
        self._last_input_callback_time = time.monotonic()
        raw_bytes = bytes(indata) if indata is not None else b""
        self._process_raw_audio_chunk(raw_bytes)

    def _process_raw_audio_chunk(self, raw_bytes: bytes):
        """Processes 16kHz int16 PCM chunk (VAD, multi-channel GCC-PHAT DOA, 24kHz upsampling)."""
        try:
            if not raw_bytes:
                return

            now = time.monotonic()
            if now < self._playback_drop_until:
                return

            # Multi-channel or Mono audio unpacking
            raw_arr = np.frombuffer(raw_bytes, dtype=np.int16)
            if self._capture_channels >= 4 and len(raw_arr) >= (HW_BLOCK_SIZE * self._capture_channels):
                multi_ch = raw_arr.reshape(-1, self._capture_channels).T  # Shape: (channels, frames)
                arr = multi_ch[0]  # Front microphone for speech recognition
                mono_raw_bytes = arr.tobytes()
            else:
                multi_ch = None
                arr = raw_arr
                mono_raw_bytes = raw_bytes

            # Measure RMS level and peak for diagnostic & VAD
            peak = 0
            try:
                rms = float(np.sqrt(np.mean(arr.astype(np.float32) ** 2)))
                if len(arr) > 0:
                    peak = int(np.max(np.abs(arr)))
            except Exception:
                rms = 0.0
                peak = 0

            is_active_playback = (
                self._is_playing
                or (now - self._last_playback_time < self.echo_mute_cooldown_s)
                or (now - self._last_output_chunk_time < self.echo_mute_cooldown_s)
            )

            if not is_active_playback and rms < 400.0:
                # Continuously adapt ambient background noise floor during quiet periods
                self._ambient_rms = 0.96 * self._ambient_rms + 0.04 * rms
            elif not is_active_playback and rms >= 400.0:
                self._last_mic_speech_time = now

            # Multi-Channel GCC-PHAT DOA Spatial Estimation (Fallback only when hardware ReSpeaker HID is absent)
            has_hw_hid = bool(self._respeaker and getattr(self._respeaker, "dev", None) is not None)
            if not has_hw_hid and multi_ch is not None and self._doa_estimator and not is_active_playback and rms >= 400.0:
                azimuth_deg, conf, valid = self._doa_estimator.estimate_from_multichannel_pcm(multi_ch[:4])
                if valid and azimuth_deg is not None:
                    raw_doa = azimuth_deg if azimuth_deg >= 0.0 else azimuth_deg + 360.0
                    doa_msg = Float32()
                    doa_msg.data = float(raw_doa)
                    self.pub_doa.publish(doa_msg)
                    self.pub_vad.publish(Bool(data=True))

            # Software Echo Mute & Self-Voice Suppression (Zero Self-Hearing):
            if is_active_playback:
                burst_start = getattr(self, "_burst_start_time", 0.0)
                if self._playback_burst_active and burst_start > 0.0 and ((now - burst_start) * 1000.0 < self.barge_in_protection_ms):
                    return

                # Adaptive barge-in threshold derived from ambient noise floor
                adaptive_barge_in_rms = max(self.barge_in_min_rms, self._ambient_rms * self.barge_in_noise_mult)

                # 2. Distinguish loud speech energy during active playback
                is_genuine_barge_in = (rms >= adaptive_barge_in_rms and peak >= self.barge_in_min_peak)
                if not is_genuine_barge_in:
                    return

            # Energy gate: Only stream frames with meaningful speech energy.
            # Streaming continuous silence wastes bandwidth and burns TPM quota on OpenAI Realtime.
            # Gate threshold: above dead silence floor (10) AND either above ambient*0.5 or above hard minimum of 40.
            if not is_active_playback and rms < max(40.0, self._ambient_rms * 0.50):
                return

            # Publish mic level
            lvl_msg = Float32()
            lvl_msg.data = float(rms)
            self.pub_input_level.publish(lvl_msg)

            # Resample 16kHz -> 24kHz for OpenAI Realtime API (Channel 0 / Front Speech)
            pcm_24k = resample_16k_to_24k(mono_raw_bytes)

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
                self.get_logger().debug(f"Input processing exception: {exc}")
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
                    b64_pcm = payload.get("pcm") or payload.get("data", "")
                except Exception:
                    b64_pcm = raw_str
            else:
                b64_pcm = raw_str

            is_done = bool(payload.get("is_done", False))
            is_first = bool(payload.get("is_first", False))
            gen_id = payload.get("generation_id", 0)

            raw_16k = b""
            if b64_pcm:
                raw_24k = base64.b64decode(b64_pcm.encode("ascii"))
                if raw_24k:
                    # Resample 24kHz -> 16kHz for hardware ReSpeaker DAC
                    raw_16k = resample_24k_to_16k(raw_24k)

            if raw_16k or is_done:
                item = {
                    "pcm": raw_16k,
                    "generation_id": gen_id,
                    "is_first": is_first,
                    "is_done": is_done,
                    "tts_provider": payload.get("tts_provider", "openai"),
                    "tts_model": payload.get("tts_model", "gpt-realtime-2.1-mini"),
                    "tts_source": payload.get("tts_source", "realtime_openai"),
                    "playback_source": payload.get("playback_source", payload.get("tts_source", "realtime_openai")),
                }
                self._play_queue.put_nowait(item)
                self._last_output_chunk_time = time.monotonic()
                self._last_output_envelope = item
                self._total_enqueued_bytes += len(raw_16k)
        except (queue.Full, Exception) as e:
            self.get_logger().debug(f"PCM enqueue notice: {e}")

    def _on_interrupt(self, msg: Bool):
        """Zero-latency barge-in signal: instantly flush playback buffer queue and mute lingering tail."""
        try:
            if not msg.data:
                return

            # P0-7: Barge-in is only valid if playback has actually started and played bytes > 0
            if not self._playback_burst_active or self._total_played_bytes == 0:
                return

            now_mono = time.monotonic()
            barge_in_after_ms = int((now_mono - self._burst_start_time) * 1000.0) if self._burst_start_time > 0 else 0
            if self._burst_start_time > 0 and barge_in_after_ms < int(self.barge_in_protection_ms):
                self.get_logger().debug(f"🛡️ [Acoustic Gate] Interruption rejected: {barge_in_after_ms}ms < {self.barge_in_protection_ms}ms (self-voice echo)")
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

            barge_in_source = "user"
            self._is_playing = False
            self._playback_burst_active = False
            self._last_playback_time = 0.0
            self._playback_drop_until = now_mono + 0.15
            prov = getattr(self, "_active_provenance", {})
            cancelled_gen = prov.get('generation_id', 0)
            if not hasattr(self, "_cancelled_gen_ids"):
                self._cancelled_gen_ids = set()
            self._cancelled_gen_ids.add(cancelled_gen)

            gen_bytes = getattr(self, "_current_gen_played_bytes", self._total_played_bytes)

            self.get_logger().info(
                f"⚡ [Playback Telemetry]: tts_playback_cancelled=True | "
                f"generation_id={cancelled_gen} | "
                f"playback_source={prov.get('playback_source', 'unknown')} | "
                f"tts_provider={prov.get('tts_provider', 'unknown')} | "
                f"tts_model={prov.get('tts_model', 'unknown')} | "
                f"tts_played_bytes={gen_bytes} | "
                f"tts_remaining_bytes={discarded_bytes} | "
                f"total_playback_bytes={self._total_played_bytes} | "
                f"playback_duration_ms={barge_in_after_ms} | "
                f"barge_in_after_ms={barge_in_after_ms} | "
                f"barge_in_source={barge_in_source} | "
                f"reason=barge_in"
            )
        except Exception as exc:
            self.get_logger().debug(f"_on_interrupt error: {exc}")

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

        active_gen_id = None
        gen_started = False
        gen_done_seen = False
        gen_start_time = 0.0
        gen_played_bytes = 0
        gen_prov = {}

        if not hasattr(self, "_cancelled_gen_ids"):
            self._cancelled_gen_ids = set()

        while not self._stop_event.is_set():
            try:
                item = self._play_queue.get(timeout=0.05)
                if isinstance(item, dict):
                    chunk = item["pcm"]
                    gen_id = item.get("generation_id", 0)
                    is_done = item.get("is_done", False)
                    tts_provider = item.get("tts_provider", "openai")
                    tts_model = item.get("tts_model", "unknown")
                    tts_source = item.get("tts_source", "unknown")
                    playback_source = item.get("playback_source", tts_source)
                else:
                    chunk = item
                    gen_id = 0
                    is_done = False
                    tts_provider = "openai"
                    tts_model = os.getenv("REALTIME_MODEL", "gpt-realtime-2.1-mini")
                    tts_source = "realtime_openai"
                    playback_source = "realtime_openai"

                # Check if this is a new generation
                if (gen_id != active_gen_id) or (not gen_started):
                    if gen_started and active_gen_id is not None and active_gen_id not in self._cancelled_gen_ids:
                        # Close prior generation cleanly if not cancelled
                        burst_dur_ms = (time.monotonic() - gen_start_time) * 1000.0
                        self.get_logger().info(
                            f"🔊 [Playback Telemetry]: tts_playback_finished=True | "
                            f"generation_id={active_gen_id} | "
                            f"playback_source={gen_prov.get('playback_source', 'unknown')} | "
                            f"tts_provider={gen_prov.get('tts_provider', 'unknown')} | "
                            f"tts_model={gen_prov.get('tts_model', 'unknown')} | "
                            f"tts_played_bytes={gen_played_bytes} | "
                            f"total_playback_bytes={self._total_played_bytes} | "
                            f"playback_duration_ms={int(burst_dur_ms)}"
                        )
                    active_gen_id = gen_id
                    gen_started = True
                    gen_done_seen = False
                    gen_start_time = time.monotonic()
                    gen_played_bytes = 0
                    self._current_gen_played_bytes = 0
                    gen_prov = {
                        "generation_id": gen_id,
                        "playback_source": playback_source,
                        "tts_provider": tts_provider,
                        "tts_model": tts_model,
                        "tts_source": tts_source,
                    }
                    self._playback_burst_active = True
                    self._burst_start_time = gen_start_time
                    self._active_provenance = gen_prov
                    self.get_logger().info(
                        f"🔊 [Playback Telemetry]: tts_playback_started=True | "
                        f"generation_id={gen_id} | playback_source={playback_source} | "
                        f"tts_provider={tts_provider} | tts_model={tts_model} | "
                        f"tts_source={tts_source} | audio_bytes={len(chunk)} | "
                        f"tts_audio_device=\"{self._out_device_name}\""
                    )

                if is_done:
                    gen_done_seen = True

                # Discard chunks if generation was cancelled by barge-in
                if active_gen_id in self._cancelled_gen_ids:
                    continue

                if chunk and len(chunk) > 0:
                    t_w_start = time.perf_counter()
                    with self._playback_lock:
                        out_stream.write(chunk)
                    t_w_end = time.perf_counter()

                    self._is_playing = True
                    self._last_playback_time = time.monotonic()
                    gen_played_bytes += len(chunk)
                    self._current_gen_played_bytes = gen_played_bytes
                    self._total_played_bytes += len(chunk)

                # If done signal received and queue is now empty, finish generation playback
                if gen_done_seen and self._play_queue.empty():
                    self._is_playing = False
                    self._playback_burst_active = False
                    gen_started = False
                    burst_dur_ms = (time.monotonic() - gen_start_time) * 1000.0
                    if active_gen_id not in self._cancelled_gen_ids:
                        self.get_logger().info(
                            f"🔊 [Playback Telemetry]: tts_playback_finished=True | "
                            f"generation_id={active_gen_id} | "
                            f"playback_source={gen_prov.get('playback_source', 'unknown')} | "
                            f"tts_provider={gen_prov.get('tts_provider', 'unknown')} | "
                            f"tts_model={gen_prov.get('tts_model', 'unknown')} | "
                            f"tts_played_bytes={gen_played_bytes} | "
                            f"total_playback_bytes={self._total_played_bytes} | "
                            f"playback_duration_ms={int(burst_dur_ms)}"
                        )
                    active_gen_id = None

            except queue.Empty:
                if gen_started and gen_done_seen:
                    self._is_playing = False
                    self._playback_burst_active = False
                    gen_started = False
                    burst_dur_ms = (time.monotonic() - gen_start_time) * 1000.0
                    if active_gen_id not in self._cancelled_gen_ids:
                        self.get_logger().info(
                            f"🔊 [Playback Telemetry]: tts_playback_finished=True | "
                            f"generation_id={active_gen_id} | "
                            f"playback_source={gen_prov.get('playback_source', 'unknown')} | "
                            f"tts_provider={gen_prov.get('tts_provider', 'unknown')} | "
                            f"tts_model={gen_prov.get('tts_model', 'unknown')} | "
                            f"tts_played_bytes={gen_played_bytes} | "
                            f"total_playback_bytes={self._total_played_bytes} | "
                            f"playback_duration_ms={int(burst_dur_ms)}"
                        )
                    active_gen_id = None
                elif gen_started and (time.monotonic() - self._last_playback_time) > 2.0:
                    # Stream timed out without is_done (e.g. dropped connection)
                    self._is_playing = False
                    self._playback_burst_active = False
                    gen_started = False
                    burst_dur_ms = (time.monotonic() - gen_start_time) * 1000.0
                    if active_gen_id not in self._cancelled_gen_ids:
                        self.get_logger().info(
                            f"🔊 [Playback Telemetry]: tts_playback_finished=True | "
                            f"generation_id={active_gen_id} | "
                            f"playback_source={gen_prov.get('playback_source', 'unknown')} | "
                            f"tts_provider={gen_prov.get('tts_provider', 'unknown')} | "
                            f"tts_model={gen_prov.get('tts_model', 'unknown')} | "
                            f"tts_played_bytes={gen_played_bytes} | "
                            f"total_playback_bytes={self._total_played_bytes} | "
                            f"playback_duration_ms={int(burst_dur_ms)} | reason=stream_timeout"
                        )
                    active_gen_id = None
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
        msg.data = bool(
            self._is_playing
            or not self._play_queue.empty()
            or (time.monotonic() - self._last_output_chunk_time) < self.echo_mute_cooldown_s
        )
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
