#!/usr/bin/env python3
"""ASTRO Robot — Standalone Interactive ReSpeaker DOA Calibration Tool.

Empirically determines the mapping between:
    physical speaker angle relative to robot
                   ↕
          raw /audio/doa angle

Subscribes directly to:
    /audio/doa            (std_msgs/Float32)  - Raw DOA angle [0..360° or -180..+180°]
    /audio/doa_confidence (std_msgs/Float32)  - Acoustic PSR confidence [0.0..1.0]
    /audio/vad            (std_msgs/Bool)     - Voice Activity Detection status

Usage:
    python3 scripts/calibrate_respeaker_doa.py
    python3 scripts/calibrate_respeaker_doa.py --positions 0,30,60,90,-30,-60,-90 --duration 3.0 --min-confidence 0.40
    python3 scripts/calibrate_respeaker_doa.py --simulate --non-interactive

Diagnostic/calibration tool only. Does NOT modify the production runtime.
"""

import argparse
from dataclasses import asdict, dataclass
import json
import math
import os
import sys
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

# Reconfigure stdout/stderr for UTF-8 compatibility across all terminal locales
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import numpy as np

try:
    import sounddevice as sd
    HAS_SOUNDDEVICE = True
except ImportError:
    sd = None
    HAS_SOUNDDEVICE = False

# Import ReSpeaker device resolver
from respeaker_device import (
    RESPEAKER_ALSA_DEVICE,
    RESPEAKER_CARD_ID,
    REQUIRED_CHANNELS,
    REQUIRED_MIC_CHANNELS,
    REQUIRED_SAMPLE_FORMAT,
    REQUIRED_SAMPLE_RATE,
    RespeakerDeviceInfo,
    resolve_respeaker_capture_device,
    validate_respeaker_device,
)

# Optional AcousticDOAEstimator for direct hardware capture
try:
    from astro_audio.doa_estimator import AcousticDOAEstimator
except ImportError:
    AcousticDOAEstimator = None

# Optional ROS 2 import
try:
    import rclpy
    from rclpy.node import Node
    from rclpy.qos import QoSProfile, ReliabilityPolicy
    from std_msgs.msg import Bool, Float32
    ROS2_AVAILABLE = True
except ImportError:
    ROS2_AVAILABLE = False
    Node = object


# Canonical acoustic parameters from ASTRO architecture
DEFAULT_POSITIONS = [0.0, 30.0, 60.0, 90.0, -30.0, -60.0, -90.0]
DEFAULT_DURATION_S = 3.0
DEFAULT_MIN_CONFIDENCE = 0.40  # Canonical min_confidence in AudioPerceptionCore & action_manager
DEFAULT_OUTPUT_PATH = "config/respeaker_doa_calibration.json"
HW_SAMPLE_RATE = REQUIRED_SAMPLE_RATE
HW_BLOCK_SIZE = 320


@dataclass
class DOASample:
    """Individual acoustic sample received during calibration."""
    timestamp: float
    raw_doa_deg: float
    confidence: float
    vad: bool


@dataclass
class PositionCalibrationResult:
    """Statistical summary for a single calibration position."""
    physical_deg: float
    sample_count: int
    mean_raw_deg: Optional[float]
    mean_signed_deg: Optional[float]
    median_raw_deg: Optional[float]
    median_signed_deg: Optional[float]
    stddev_deg: Optional[float]
    confidence_mean: float
    valid_ratio: float
    min_raw_deg: Optional[float]
    max_raw_deg: Optional[float]
    total_received: int
    is_stable: bool
    status_msg: str

    def to_json_dict(self) -> Dict[str, Optional[float]]:
        """Converts result to schema requested for config output."""
        return {
            "physical_deg": self.physical_deg,
            "mean_raw_deg": self.mean_raw_deg,
            "median_raw_deg": self.median_raw_deg,
            "stddev_deg": self.stddev_deg,
            "confidence_mean": self.confidence_mean,
            "valid_ratio": self.valid_ratio,
            "mean_signed_deg": self.mean_signed_deg,
            "median_signed_deg": self.median_signed_deg,
            "min_raw_deg": self.min_raw_deg,
            "max_raw_deg": self.max_raw_deg,
            "sample_count": self.sample_count,
            "total_received": self.total_received,
        }


def compute_circular_stats(
    samples: List[DOASample],
    physical_deg: float = 0.0,
    min_confidence: float = DEFAULT_MIN_CONFIDENCE,
) -> PositionCalibrationResult:
    """Computes circular angle statistics and acoustic validity metrics.

    Handles boundary wrapping so that tight clusters like [359°, 0°, 1°]
    are resolved to ~0° mean and low variance (~1.0° stddev) rather than
    spurious ~120° mean and >100° variance.

    Args:
        samples: List of DOASample objects captured during window.
        physical_deg: Physical ground-truth angle of speaker relative to robot.
        min_confidence: Threshold for accepting a sample as valid acoustic data.

    Returns:
        PositionCalibrationResult with all statistics and stability assessment.
    """
    total_count = len(samples)
    valid_samples = [
        s for s in samples
        if s.vad and (s.confidence >= min_confidence) and math.isfinite(s.raw_doa_deg)
    ]
    valid_count = len(valid_samples)
    valid_ratio = round(valid_count / total_count, 3) if total_count > 0 else 0.0

    if valid_count == 0:
        return PositionCalibrationResult(
            physical_deg=physical_deg,
            sample_count=0,
            mean_raw_deg=None,
            mean_signed_deg=None,
            median_raw_deg=None,
            median_signed_deg=None,
            stddev_deg=None,
            confidence_mean=0.0,
            valid_ratio=valid_ratio,
            min_raw_deg=None,
            max_raw_deg=None,
            total_received=total_count,
            is_stable=False,
            status_msg="NO_VALID_SPEECH (0 valid samples meet VAD & confidence)",
        )

    angles_deg = [s.raw_doa_deg for s in valid_samples]
    confs = [s.confidence for s in valid_samples]
    conf_mean = round(float(np.mean(confs)), 3)

    # Convert to radians on unit circle
    rads = np.deg2rad(angles_deg)
    s = float(np.sum(np.sin(rads)))
    c = float(np.sum(np.cos(rads)))
    n = len(angles_deg)

    # Circular mean angle
    mean_rad = math.atan2(s, c)
    mean_deg_360 = (math.degrees(mean_rad)) % 360.0
    if abs(mean_deg_360 - 360.0) < 1e-7:
        mean_deg_360 = 0.0
    mean_deg_pm180 = ((math.degrees(mean_rad) + 180.0) % 360.0) - 180.0
    if abs(mean_deg_pm180 - 180.0) < 1e-7:
        mean_deg_pm180 = 180.0

    # Angular deviations delta_i in [-180, +180] relative to circular mean
    deltas = [((a - mean_deg_360 + 180.0) % 360.0) - 180.0 for a in angles_deg]

    # Sample standard deviation of unwrapped angular deviations
    if n > 1:
        sample_stddev = float(np.sqrt(sum(d**2 for d in deltas) / (n - 1)))
    else:
        sample_stddev = 0.0

    # Circular median via median angular delta
    median_delta = float(np.median(deltas))
    median_deg_360 = (mean_deg_360 + median_delta) % 360.0
    if abs(median_deg_360 - 360.0) < 1e-7:
        median_deg_360 = 0.0
    median_deg_pm180 = ((mean_deg_pm180 + median_delta + 180.0) % 360.0) - 180.0

    # Minimum and Maximum unwrapped angles relative to circular mean
    min_delta = min(deltas)
    max_delta = max(deltas)
    min_raw = (mean_deg_360 + min_delta) % 360.0
    max_raw = (mean_deg_360 + max_delta) % 360.0

    # Stability assessment: distinguish incorrect-but-stable from unstable
    is_stable = (valid_ratio >= 0.60) and (sample_stddev <= 15.0)
    if is_stable:
        offset = mean_deg_pm180 - physical_deg
        # Wrap offset to [-180, 180]
        offset = ((offset + 180.0) % 360.0) - 180.0
        status_msg = f"STABLE (offset: {offset:+.1f}°, stddev: {sample_stddev:.1f}°)"
    elif sample_stddev > 25.0:
        status_msg = f"UNSTABLE (high spread stddev: {sample_stddev:.1f}°)"
    else:
        status_msg = f"LOW_SAMPLE_COUNT (valid ratio: {valid_ratio*100:.1f}%)"

    return PositionCalibrationResult(
        physical_deg=physical_deg,
        sample_count=valid_count,
        mean_raw_deg=round(mean_deg_360, 2),
        mean_signed_deg=round(mean_deg_pm180, 2),
        median_raw_deg=round(median_deg_360, 2),
        median_signed_deg=round(median_deg_pm180, 2),
        stddev_deg=round(sample_stddev, 2),
        confidence_mean=conf_mean,
        valid_ratio=valid_ratio,
        min_raw_deg=round(min_raw, 2),
        max_raw_deg=round(max_raw, 2),
        total_received=total_count,
        is_stable=is_stable,
        status_msg=status_msg,
    )


if ROS2_AVAILABLE:
    class DOAListenerNode(Node):
        """ROS 2 Node subscribing to /audio/doa, /audio/doa_confidence, and /audio/vad."""

        def __init__(self):
            super().__init__("respeaker_doa_calibrator")
            self._lock = threading.Lock()
            self._recording = False
            self._captured_samples: List[DOASample] = []

            self._latest_conf: float = 0.0
            self._latest_conf_time: float = 0.0
            self._latest_vad: bool = False
            self._latest_vad_time: float = 0.0

            # Subscriptions
            self.sub_doa = self.create_subscription(
                Float32, "/audio/doa", self._on_doa, 10
            )
            self.sub_conf = self.create_subscription(
                Float32, "/audio/doa_confidence", self._on_conf, 10
            )
            self.sub_vad = self.create_subscription(
                Bool, "/audio/vad", self._on_vad, 10
            )
            self.get_logger().info("DOAListenerNode initialized, subscribed to /audio/doa topics.")

        def _on_conf(self, msg: Float32) -> None:
            with self._lock:
                self._latest_conf = float(msg.data)
                self._latest_conf_time = time.monotonic()

        def _on_vad(self, msg: Bool) -> None:
            with self._lock:
                self._latest_vad = bool(msg.data)
                self._latest_vad_time = time.monotonic()

        def _on_doa(self, msg: Float32) -> None:
            now = time.monotonic()
            val = float(msg.data)
            with self._lock:
                if not self._recording:
                    return
                # Latch contemporaneous confidence and VAD within freshness threshold (1.0s)
                conf = self._latest_conf if (now - self._latest_conf_time) <= 1.0 else 0.0
                vad = self._latest_vad if (now - self._latest_vad_time) <= 1.0 else False

                sample = DOASample(
                    timestamp=now,
                    raw_doa_deg=val,
                    confidence=conf,
                    vad=vad,
                )
                self._captured_samples.append(sample)

        def start_recording(self) -> None:
            with self._lock:
                self._captured_samples.clear()
                self._recording = True

        def stop_recording(self) -> List[DOASample]:
            with self._lock:
                self._recording = False
                return list(self._captured_samples)


def run_simulated_capture(
    physical_deg: float,
    duration_s: float,
    sample_rate_hz: float = 25.0,
    seed: Optional[int] = None,
) -> List[DOASample]:
    """Generates synthetic DOA samples corresponding to a physical speaker.

    Simulates realistic acoustic propagation:
    - Ground truth circular mapping: 0° -> 0°, +90° -> 90°, -90° -> 270°
    - Small Gaussian measurement noise (stddev ~2.0°)
    - Occasional room echo/reflection (~5% of samples)
    - Realistic VAD activity and confidence (~0.80..0.90)
    """
    if seed is None:
        seed = int(abs(physical_deg) * 100 + duration_s * 10)
    rng = np.random.default_rng(seed)

    # Nominal ReSpeaker circular mapping
    nominal_circ = (physical_deg) % 360.0

    total_samples = int(duration_s * sample_rate_hz)
    samples: List[DOASample] = []
    t = time.monotonic()

    for _ in range(total_samples):
        t += 1.0 / sample_rate_hz
        is_reflection = rng.random() < 0.05
        is_speech = rng.random() > 0.05  # 95% active speech

        if is_speech:
            if is_reflection:
                # Reflection scattered off room boundary
                raw_angle = (nominal_circ + rng.uniform(-60.0, 60.0)) % 360.0
                conf = float(rng.uniform(0.20, 0.40))
                vad = True
            else:
                # Direct path signal with low acoustic jitter
                raw_angle = (nominal_circ + rng.normal(0.0, 2.2)) % 360.0
                conf = float(np.clip(rng.normal(0.82, 0.05), 0.45, 0.98))
                vad = True
        else:
            # Silence / ambient noise
            raw_angle = float(rng.uniform(0.0, 360.0))
            conf = float(rng.uniform(0.05, 0.25))
            vad = False

        samples.append(DOASample(timestamp=t, raw_doa_deg=raw_angle, confidence=conf, vad=vad))

    return samples


class ReSpeakerHardwareCapture:
    """Captures 6 channels, 16000 Hz, S16_LE from hw:CARD=ArrayUAC10,DEV=0 and estimates DOA via GCC-PHAT."""

    def __init__(self, device_info: RespeakerDeviceInfo):
        self.device_info = device_info
        if AcousticDOAEstimator is None:
            raise RuntimeError("AcousticDOAEstimator is required for hardware capture mode.")
        self.estimator = AcousticDOAEstimator(sample_rate=device_info.sample_rate)
        self._lock = threading.Lock()
        self._recording = False
        self._captured_samples: List[DOASample] = []
        self._stream = None

    def start(self) -> None:
        if not HAS_SOUNDDEVICE or sd is None:
            raise RuntimeError("sounddevice is not available.")
        self._stream = sd.RawInputStream(
            samplerate=self.device_info.sample_rate,
            blocksize=HW_BLOCK_SIZE,
            device=self.device_info.device_index,
            channels=self.device_info.channels,
            dtype="int16",
            callback=self._input_callback,
        )
        self._stream.start()

    def _input_callback(self, indata, frames, time_info, status):
        if not self._recording or indata is None:
            return
        now = time.monotonic()
        raw_arr = np.frombuffer(bytes(indata), dtype=np.int16)
        if len(raw_arr) < (HW_BLOCK_SIZE * self.device_info.channels):
            return
        multi_ch = raw_arr.reshape(-1, self.device_info.channels).T  # Shape: (channels, frames)

        # Extract verified raw mic channels [1, 2, 3, 4]
        mics = multi_ch[list(self.device_info.mic_indices)]
        mono = np.mean(mics.astype(np.float32), axis=0)
        rms = float(np.sqrt(np.mean(mono ** 2)))
        peak = float(np.max(np.abs(mono)))
        is_speech = (rms >= 250.0) and (peak >= 700.0)

        azimuth_deg, conf, valid = self.estimator.estimate_from_multichannel_pcm(mics)
        if valid and azimuth_deg is not None:
            raw_doa = azimuth_deg if azimuth_deg >= 0.0 else azimuth_deg + 360.0
        else:
            raw_doa = float(azimuth_deg or 0.0)

        with self._lock:
            if self._recording:
                self._captured_samples.append(
                    DOASample(
                        timestamp=now,
                        raw_doa_deg=raw_doa,
                        confidence=float(conf),
                        vad=is_speech and valid,
                    )
                )

    def start_recording(self) -> None:
        with self._lock:
            self._captured_samples.clear()
            self._recording = True

    def stop_recording(self) -> List[DOASample]:
        with self._lock:
            self._recording = False
            return list(self._captured_samples)

    def close(self) -> None:
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass


def run_calibration_session(
    positions: List[float],
    duration_s: float,
    min_confidence: float,
    output_path: str,
    simulate: bool = False,
    non_interactive: bool = False,
    mode: str = "hardware",
    device_override: Optional[Any] = None,
) -> List[PositionCalibrationResult]:
    """Runs the interactive calibration workflow across all requested physical angles."""

    results: List[PositionCalibrationResult] = []
    listener_node: Optional[Any] = None
    spin_thread: Optional[threading.Thread] = None
    hw_capture: Optional[ReSpeakerHardwareCapture] = None

    if not simulate:
        if mode == "ros":
            if not ROS2_AVAILABLE:
                print("❌ ROS 2 (rclpy) is not available in this environment.")
                print("   To run with direct hardware capture, run with --mode hardware.")
                print("   To test in simulation mode, run with --simulate.")
                sys.exit(1)

            rclpy.init()
            listener_node = DOAListenerNode()
            spin_thread = threading.Thread(target=rclpy.spin, args=(listener_node,), daemon=True)
            spin_thread.start()
        else:
            # Mode "hardware": Direct deterministic capture from hw:CARD=ArrayUAC10,DEV=0
            device_info = resolve_respeaker_capture_device(
                allow_simulation=simulate,
                device_override=device_override,
            )
            if not validate_respeaker_device(device_info):
                sys.exit(1)

            hw_capture = ReSpeakerHardwareCapture(device_info)
            hw_capture.start()

    try:
        for idx, pos in enumerate(positions, 1):
            pos_sign_str = f"+{pos:.0f}°" if pos > 0 else f"{pos:.0f}°"

            print("\n" + "=" * 40)
            print(" ASTRO ReSpeaker DOA Calibration")
            print("=" * 40)
            print(f"\nCurrent calibration position: {pos_sign_str}")
            print(f"Stand at {pos_sign_str} relative to robot.")

            if not non_interactive:
                try:
                    input("\nPress ENTER when ready...")
                except (EOFError, KeyboardInterrupt):
                    print("\nCalibration aborted by user.")
                    break
            else:
                print("\n[Auto-mode] Proceeding with capture...")

            print(f"Capturing DOA samples for {duration_s:.1f} seconds (please speak continuously)...")

            if simulate:
                time.sleep(min(duration_s, 0.2) if non_interactive else duration_s)
                samples = run_simulated_capture(physical_deg=pos, duration_s=duration_s)
            elif hw_capture is not None:
                hw_capture.start_recording()
                time.sleep(duration_s)
                samples = hw_capture.stop_recording()
            else:
                assert listener_node is not None
                listener_node.start_recording()
                time.sleep(duration_s)
                samples = listener_node.stop_recording()

            # Compute stats
            pos_res = compute_circular_stats(
                samples=samples,
                physical_deg=pos,
                min_confidence=min_confidence,
            )
            results.append(pos_res)

            # Display individual position result
            print(f"\nRESULT {pos_sign_str}")
            print(f"samples: {pos_res.sample_count}")
            if pos_res.sample_count > 0:
                print(f"mean:    {pos_res.mean_raw_deg:.1f}°")
                print(f"median:  {pos_res.median_raw_deg:.1f}°")
                print(f"stddev:  {pos_res.stddev_deg:.1f}°")
                print(f"min:     {pos_res.min_raw_deg:.1f}°")
                print(f"max:     {pos_res.max_raw_deg:.1f}°")
                print(f"confidence:  {pos_res.confidence_mean:.2f}")
                print(f"valid ratio: {pos_res.valid_ratio * 100:.1f}%")
            else:
                print(f"status:  {pos_res.status_msg}")

            if idx < len(positions) and not non_interactive:
                try:
                    input("\nPress ENTER for next calibration position...")
                except (EOFError, KeyboardInterrupt):
                    print("\nCalibration ended early.")
                    break

    finally:
        if hw_capture is not None:
            hw_capture.close()
        if listener_node is not None and ROS2_AVAILABLE:
            listener_node.destroy_node()
            if rclpy.ok():
                rclpy.shutdown()

    # Complete summary table
    print("\n" + "=" * 55)
    print(f"{'PHYSICAL':<10} {'RAW MEAN':<12} {'RAW MEDIAN':<12} {'STDDEV':<10} {'SAMPLES':<8}")
    print("-" * 55)
    for r in results:
        p_str = f"+{r.physical_deg:.0f}°" if r.physical_deg > 0 else f"{r.physical_deg:.0f}°"
        m_str = f"{r.mean_raw_deg:.1f}°" if r.mean_raw_deg is not None else "N/A"
        med_str = f"{r.median_raw_deg:.1f}°" if r.median_raw_deg is not None else "N/A"
        std_str = f"{r.stddev_deg:.1f}°" if r.stddev_deg is not None else "N/A"
        print(f"{p_str:<10} {m_str:<12} {med_str:<12} {std_str:<10} {r.sample_count:<8}")

    # Final detailed report
    print("\n" + "=" * 48)
    print(" ASTRO DOA CALIBRATION SUMMARY")
    print("=" * 48 + "\n")

    for r in results:
        p_str = f"+{r.physical_deg:.0f}°" if r.physical_deg > 0 else f"{r.physical_deg:.0f}°"
        print(f"Physical {p_str}:")
        if r.sample_count > 0:
            print(f"  DOA mean:        {r.mean_raw_deg:.1f}° (signed: {r.mean_signed_deg:+.1f}°)")
            print(f"  DOA median:      {r.median_raw_deg:.1f}° (signed: {r.median_signed_deg:+.1f}°)")
            print(f"  DOA circular SD: {r.stddev_deg:.1f}°")
            print(f"  confidence mean: {r.confidence_mean:.2f}")
            print(f"  valid sample ratio: {r.valid_ratio * 100:.1f}% ({r.sample_count}/{r.total_received})")
            print(f"  assessment:      {r.status_msg}")
        else:
            print(f"  {r.status_msg}")
        print()

    print("=" * 48)
    print("Observed mapping:")
    print("physical -> raw")
    for r in results:
        p_str = f"{r.physical_deg:+.0f}°" if r.physical_deg != 0 else "  0°"
        if r.mean_raw_deg is not None and r.mean_signed_deg is not None:
            print(f"  {p_str:>5} -> {r.mean_raw_deg:5.1f}° ({r.mean_signed_deg:+5.1f}°) "
                  f"[stddev={r.stddev_deg:.1f}°, conf={r.confidence_mean:.2f}]")
        else:
            print(f"  {p_str:>5} -> [NO SAMPLES]")
    print()

    # Save to JSON output
    out_dir = os.path.dirname(output_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    json_payload = {
        "calibration_timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "duration_s": duration_s,
        "min_confidence": min_confidence,
        "positions_deg": [r.to_json_dict() for r in results],
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(json_payload, f, indent=2)

    print(f"📁 Calibration results saved to: {output_path}")
    return results


def parse_positions(pos_str: str) -> List[float]:
    """Parses a comma-separated list of float angles."""
    try:
        return [float(p.strip()) for p in pos_str.split(",") if p.strip()]
    except ValueError as e:
        raise argparse.ArgumentTypeError(f"Invalid position list '{pos_str}': {e}")


def main():
    parser = argparse.ArgumentParser(
        description="ASTRO ReSpeaker DOA Interactive Calibration Tool",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--positions",
        type=parse_positions,
        default=DEFAULT_POSITIONS,
        help="Comma-separated physical calibration angles in degrees",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=DEFAULT_DURATION_S,
        help="Capture window duration in seconds per position",
    )
    parser.add_argument(
        "--min-confidence",
        type=float,
        default=DEFAULT_MIN_CONFIDENCE,
        help="Minimum acoustic confidence threshold for valid samples",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=DEFAULT_OUTPUT_PATH,
        help="Path to save JSON calibration results",
    )
    parser.add_argument(
        "--mode",
        choices=["hardware", "ros"],
        default="hardware",
        help="Capture mode: 'hardware' (direct ReSpeaker ALSA ArrayUAC10 capture) or 'ros' (subscribe to /audio/doa)",
    )
    parser.add_argument(
        "--device",
        type=str,
        default=None,
        help="Explicit ALSA capture device name or index (defaults to ReSpeaker hw:CARD=ArrayUAC10,DEV=0)",
    )
    parser.add_argument(
        "--simulate",
        action="store_true",
        help="Run in simulation mode without hardware or ROS 2 daemon",
    )
    parser.add_argument(
        "--non-interactive",
        action="store_true",
        help="Run automatically without waiting for ENTER keypresses",
    )

    args = parser.parse_args()

    run_calibration_session(
        positions=args.positions,
        duration_s=args.duration,
        min_confidence=args.min_confidence,
        output_path=args.output,
        simulate=args.simulate,
        non_interactive=args.non_interactive,
        mode=args.mode,
        device_override=args.device,
    )


if __name__ == "__main__":
    main()
