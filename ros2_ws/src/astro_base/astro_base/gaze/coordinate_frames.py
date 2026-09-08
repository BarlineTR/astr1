"""Coordinate Frames, Kinematic Transformations, and Calibration for ASTRO Gaze.

Defines mathematical conversions between:
  - `oak_rgb_camera_optical_frame` (REP-103: +Z forward, +X right, +Y down)
  - `mic_link` (ReSpeaker 4-mic circular array frame)
  - `head_link` / `head_yaw_link` (Robot head pan frame)
  - `base_link` (Robot mobile chassis base frame)
  - `world` / `odom` (Global navigation frame)
"""

import math
from dataclasses import dataclass, field
from typing import Optional, Tuple
import yaml

from astro_base.gaze.angle_math import clamp_deg, wrap_deg


@dataclass
class HeadCalibration:
    """Head mechanical joint calibration parameters."""
    zero_offset_deg: float = 0.0
    # 440 tick / 170 derece: boyun ±85 dönüyor. Kalibrasyon dosyası okunmadığında
    # da bundan daha çekingen olmamalı, yoksa kafa erişebileceği kişide duruyor.
    min_angle_deg: float = -85.0
    max_angle_deg: float = 85.0
    ticks_per_deg: float = 1.5000









@dataclass
class AudioCalibration:
    """Microphone array mounting and calibration parameters."""
    yaw_offset_deg: float = 0.0
    invert: bool = True  # ReSpeaker measures clockwise; REP-103 is CCW (positive=left)


@dataclass
class CameraCalibration:
    """OAK-D Lite camera mounting and optical calibration parameters."""
    yaw_offset_deg: float = 0.0
    pitch_offset_deg: float = 0.0
    hfov_deg: float = 72.0
    vfov_deg: float = 53.0
    focal_length_px: float = 512.0  # Approx for 640x480 resolution


@dataclass
class CalibrationConfig:
    """Unified system calibration configuration."""
    head: HeadCalibration = field(default_factory=HeadCalibration)
    audio: AudioCalibration = field(default_factory=AudioCalibration)
    camera: CameraCalibration = field(default_factory=CameraCalibration)

    @classmethod
    def from_dict(cls, data: dict) -> "CalibrationConfig":
        if "ros__parameters" in data:
            data = data["ros__parameters"]
        elif "/**" in data and isinstance(data["/**"], dict) and "ros__parameters" in data["/**"]:
            data = data["/**"]["ros__parameters"]

        cfg = cls()
        if "head" in data:
            h = data["head"]

            cfg.head = HeadCalibration(
                zero_offset_deg=float(h.get("zero_offset_deg", 0.0)),
                min_angle_deg=float(h.get("min_angle_deg", -90.0)),
                max_angle_deg=float(h.get("max_angle_deg", 90.0)),
                ticks_per_deg=float(h.get("ticks_per_deg", 2.5882)),
            )
        if "audio" in data:
            a = data["audio"]
            cfg.audio = AudioCalibration(
                yaw_offset_deg=float(a.get("yaw_offset_deg", 0.0)),
                invert=bool(a.get("invert", True)),
            )
        if "camera" in data:
            c = data["camera"]
            cfg.camera = CameraCalibration(
                yaw_offset_deg=float(c.get("yaw_offset_deg", 0.0)),
                pitch_offset_deg=float(c.get("pitch_offset_deg", 0.0)),
                hfov_deg=float(c.get("hfov_deg", 72.0)),
                vfov_deg=float(c.get("vfov_deg", 53.0)),
                focal_length_px=float(c.get("focal_length_px", 512.0)),
            )
        return cfg

    @classmethod
    def load_yaml(cls, yaml_path: str) -> "CalibrationConfig":
        with open(yaml_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return cls.from_dict(data)

    @classmethod
    def from_yaml_file(cls, yaml_path: str) -> "CalibrationConfig":
        return cls.load_yaml(yaml_path)


    def to_dict(self) -> dict:
        return {
            "head": {
                "zero_offset_deg": self.head.zero_offset_deg,
                "min_angle_deg": self.head.min_angle_deg,
                "max_angle_deg": self.head.max_angle_deg,
                "ticks_per_deg": self.head.ticks_per_deg,
            },
            "audio": {
                "yaw_offset_deg": self.audio.yaw_offset_deg,
                "invert": self.audio.invert,
            },
            "camera": {
                "yaw_offset_deg": self.camera.yaw_offset_deg,
                "pitch_offset_deg": self.camera.pitch_offset_deg,
                "hfov_deg": self.camera.hfov_deg,
                "vfov_deg": self.camera.vfov_deg,
                "focal_length_px": self.camera.focal_length_px,
            },
        }

    def save_yaml(self, yaml_path: str) -> None:
        with open(yaml_path, "w", encoding="utf-8") as f:
            yaml.dump(self.to_dict(), f, default_flow_style=False)


class CoordinateTransformer:
    """Transforms sensor observations between Camera, Microphone, Head, and Base frames."""

    def __init__(self, calib: Optional[CalibrationConfig] = None):
        self.calib = calib or CalibrationConfig()
        self._audio_sector: str = "CENTER"
        self._candidate_sector: Optional[str] = None
        self._candidate_count: int = 0
        self.persistence_threshold: int = 3

    def raw_audio_doa_to_head_bearing(self, raw_doa_deg: float) -> float:
        """Transforms raw ReSpeaker HID DOA (0..359°) into an IDLE visual search cue.

        Applies state-dependent hysteresis across 3 discrete sectors with
        a 3-consecutive-sample persistence filter to steer the head into
        the speaker's sector so OAK-D Lite can acquire the face.
        """
        raw = float(raw_doa_deg) % 360.0
        current = self._audio_sector

        # 1. State-dependent sector classification with hysteresis
        if current == "CENTER":
            if raw > 95.0:
                target = "RIGHT"
            elif raw < 55.0 or raw > 300.0:
                target = "LEFT"
            else:
                target = "CENTER"
        elif current == "RIGHT":
            if raw < 55.0 or raw > 300.0:
                target = "LEFT"
            elif raw < 88.0:
                target = "CENTER"
            else:
                target = "RIGHT"  # Retain RIGHT in 88°..95° deadband
        elif current == "LEFT":
            if raw > 95.0:
                target = "RIGHT"
            elif 58.0 <= raw <= 88.0:
                target = "CENTER"
            else:
                target = "LEFT"  # Retain LEFT in 55°..58° and >300° wrap-around
        else:
            target = "CENTER"

        # 2. 3-consecutive-sample persistence filter
        if target != current:
            if target == self._candidate_sector:
                self._candidate_count += 1
            else:
                self._candidate_sector = target
                self._candidate_count = 1

            if self._candidate_count >= self.persistence_threshold:
                self._audio_sector = target
                self._candidate_sector = None
                self._candidate_count = 0
        else:
            self._candidate_sector = None
            self._candidate_count = 0

        # 3. Discrete search yaw mapped to sectors & clamped to [-75°, +75°]
        if self._audio_sector == "RIGHT":
            yaw = 55.0
        elif self._audio_sector == "LEFT":
            yaw = -55.0
        else:
            yaw = 0.0

        return float(clamp_deg(yaw, -75.0, 75.0))

    def audio_head_bearing_to_body_yaw(
        self,
        head_relative_bearing_deg: float,
        actual_head_yaw_deg: float
    ) -> float:
        """Transforms head-relative acoustic bearing into absolute robot body yaw frame."""
        return wrap_deg(actual_head_yaw_deg + head_relative_bearing_deg)

    def raw_audio_to_body_yaw(
        self,
        raw_doa_deg: float,
        actual_head_yaw_deg: float
    ) -> float:
        """Full pipeline: Raw ReSpeaker DOA -> Robot body yaw."""
        head_rel = self.raw_audio_doa_to_head_bearing(raw_doa_deg)
        return self.audio_head_bearing_to_body_yaw(head_rel, actual_head_yaw_deg)

    def camera_pixel_to_optical_angles(
        self,
        u_px: float,
        v_px: float,
        frame_width: int,
        frame_height: int
    ) -> Tuple[float, float]:
        """Converts 2D pixel coordinates (u, v) into optical angles relative to camera axis.

        Returns:
          (cam_azimuth_deg, cam_elevation_deg)
          - cam_azimuth_deg: positive=Left, negative=Right (in robot yaw sense)
          - cam_elevation_deg: positive=Up, negative=Down
        """
        cx = frame_width / 2.0
        cy = frame_height / 2.0
        norm_u = (u_px - cx) / cx  # [-1.0..+1.0], +1 is right
        norm_v = (v_px - cy) / cy  # [-1.0..+1.0], +1 is down

        # Image right (+norm_u) corresponds to negative robot yaw (turn right)
        half_hfov = self.calib.camera.hfov_deg / 2.0
        half_vfov = self.calib.camera.vfov_deg / 2.0

        azimuth = float(-norm_u * half_hfov + self.calib.camera.yaw_offset_deg)
        elevation = float(-norm_v * half_vfov + self.calib.camera.pitch_offset_deg)

        return azimuth, elevation

    def camera_bearing_to_body_yaw(
        self,
        cam_azimuth_deg: float,
        actual_head_yaw_deg: float
    ) -> float:
        """Transforms camera-relative azimuth into absolute robot body yaw."""
        return wrap_deg(actual_head_yaw_deg + cam_azimuth_deg)

    def camera_point_to_body_frame(
        self,
        pos_3d_cam: Tuple[float, float, float],
        actual_head_yaw_deg: float
    ) -> Tuple[float, float, float]:
        """Transforms 3D optical camera coordinates (x_opt, y_opt, z_opt) to robot base frame (x, y, z).

        Optical frame (REP-103):
          x_opt: Right
          y_opt: Down
          z_opt: Forward

        Head frame:
          x_head = z_opt + 0.06 (camera forward offset)
          y_head = -x_opt (left is +Y)
          z_head = -y_opt + 0.02 (up is +Z)

        Base frame (rotated by actual_head_yaw_deg about Z):
          x_base = x_head * cos(theta) - y_head * sin(theta)
          y_base = x_head * sin(theta) + y_head * cos(theta)
          z_base = z_head + 0.21 (head height)
        """
        x_opt, y_opt, z_opt = pos_3d_cam

        x_head = z_opt + 0.06
        y_head = -x_opt
        z_head = -y_opt + 0.02

        theta_rad = math.radians(actual_head_yaw_deg)
        cos_t = math.cos(theta_rad)
        sin_t = math.sin(theta_rad)

        x_base = x_head * cos_t - y_head * sin_t
        y_base = x_head * sin_t + y_head * cos_t
        z_base = z_head + 0.21

        return float(x_base), float(y_base), float(z_base)
