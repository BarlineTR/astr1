#!/usr/bin/env python3
"""Camera and microphone, read directly rather than through ROS topics.

Both detectors are the shared ones: YuNet via astro_vision.detection_quality, and
GCC-PHAT via astro_audio.doa_estimator. Nothing about perception is reimplemented
here — this file only opens the devices and hands their output on.

Neither device is required. Running with no ReSpeaker, or no camera, degrades the
program instead of stopping it, because a tool for answering "is it the algorithms
or the plumbing?" is worth little if it only runs on the finished robot.
"""

import os
import threading
from typing import Callable, List, Optional, Tuple

import cv2
import numpy as np

import core_path  # noqa: F401
from astro_audio.doa_estimator import AcousticDOAEstimator  # noqa: E402
from astro_vision.detection_quality import create_face_detector  # noqa: E402

from tracker import Detection  # noqa: E402

SAMPLE_RATE = 16000
BLOCK_SAMPLES = 1024
# Below this the block is background noise and GCC-PHAT would localise the room.
MIN_RMS = 300.0


def to_detections(found) -> List[Detection]:
    """Turns the detector's (x, y, w, h, confidence) tuples into Detections."""
    return [
        Detection(x=int(x), y=int(y), w=int(w), h=int(h), confidence=float(conf))
        for (x, y, w, h, conf) in found
    ]


class CameraSource:
    """A webcam plus the shared face detector."""

    def __init__(self, device: int = 0, width: int = 640, height: int = 480, capture=None):
        self.capture = capture if capture is not None else cv2.VideoCapture(device)
        self.available = bool(self.capture.isOpened())
        if self.available:
            self.capture.set(cv2.CAP_PROP_FRAME_WIDTH, width)
            self.capture.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
            self.capture.set(cv2.CAP_PROP_FPS, 30.0)

        model_dir = os.path.expanduser(os.getenv("FACE_MODEL_DIR", "~/.astro/models"))
        cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        )
        self.detector = create_face_detector(model_dir, cascade)

    @property
    def detector_name(self) -> str:
        return type(self.detector).__name__

    def read(self) -> Tuple[bool, Optional[np.ndarray]]:
        if not self.available:
            return False, None
        return self.capture.read()

    def detect(self, frame) -> List[Detection]:
        return to_detections(self.detector.detect(frame))

    def close(self) -> None:
        try:
            self.capture.release()
        except Exception:
            pass


class AudioSource:
    """A 4-channel microphone array reduced to one bearing at a time.

    The estimator needs the ReSpeaker's four channels; with fewer there is no
    geometry to solve and no bearing is offered. A bearing also expires: a DOA from
    a second ago says nothing about where the talker is now, and the fusion stage
    would rather have nothing than something stale.
    """

    def __init__(
        self,
        device: Optional[int] = None,
        max_age_s: float = 0.5,
        stream_factory: Optional[Callable] = None,
    ):
        self.device = device
        self.max_age_s = max_age_s
        self._stream_factory = stream_factory
        self._estimator = AcousticDOAEstimator(sample_rate=SAMPLE_RATE)
        self._lock = threading.Lock()
        self._doa: Optional[float] = None
        self._stamp: float = 0.0
        self._stream = None
        self.available = False
        self.error: Optional[str] = None

    def start(self) -> None:
        try:
            factory = self._stream_factory
            if factory is None:
                import sounddevice

                factory = sounddevice.InputStream
            self._stream = factory(
                device=self.device, channels=4, samplerate=SAMPLE_RATE,
                blocksize=BLOCK_SAMPLES, dtype="float32", callback=self._on_block,
            )
            self._stream.start()
            self.available = True
        except Exception as exc:
            self.error = str(exc)
            self.available = False

    def _on_block(self, indata, _frames, time_info, _status):
        import time as _time

        self.process_block(np.array(indata, copy=True), timestamp=_time.monotonic())

    def process_block(self, block: np.ndarray, timestamp: float) -> None:
        """Localises one block, if it has the channels and the energy to justify it."""
        if block.ndim != 2 or min(block.shape) < 4:
            return
        channels = block.T if block.shape[0] > block.shape[1] else block
        if float(np.sqrt(np.mean(np.square(channels)))) < MIN_RMS:
            return

        azimuth, _confidence, valid = self._estimator.estimate_from_multichannel_pcm(
            channels[:4]
        )
        if valid and azimuth is not None:
            self._publish(azimuth if azimuth >= 0.0 else azimuth + 360.0, timestamp)

    def _publish(self, doa_deg: float, timestamp: float) -> None:
        with self._lock:
            self._doa, self._stamp = float(doa_deg), float(timestamp)

    def latest_doa_deg(self, now: float) -> Optional[float]:
        with self._lock:
            if self._doa is None or (now - self._stamp) > self.max_age_s:
                return None
            return self._doa

    def close(self) -> None:
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
