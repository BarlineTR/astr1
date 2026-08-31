"""Data contracts, type definitions, and enums for the ASTRO Gaze & Tracking system.

All structures use pure Python dataclasses and enums with standard SI units:
  - Angles in degrees (°), internally wrapped to (-180.0, +180.0]
  - Distances in meters (m)
  - Velocities in degrees/second (°/s) or meters/second (m/s)
  - Accelerations in degrees/second² (°/s²)
  - Jerk in degrees/second³ (°/s³)
  - Timestamps in monotonic seconds (float)
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Tuple


class Modality(str, Enum):
    """Sensing modality originating target observations."""
    NONE = "NONE"
    AUDIO = "AUDIO"
    VISION = "VISION"
    FUSED = "FUSED"
    RADAR = "RADAR"


class TrackingState(str, Enum):
    """Lifecycle state of a tracked target."""
    DETECTED = "DETECTED"    # Tentative first observation
    TRACKING = "TRACKING"    # Confirmed active track with consistent updates
    COASTING = "COASTING"    # Temporarily unobserved; predictive state extrapolation
    LOST = "LOST"            # Expired track exceeding coast timeout


class GazeStateEnum(str, Enum):
    """9-State Social Gaze Finite State Machine (FSM)."""
    IDLE = "IDLE"                        # Resting neutral pose with gentle social breathing
    SEARCHING = "SEARCHING"              # Evaluating candidate audio/radar cues
    AUDIO_ACQUIRE = "AUDIO_ACQUIRE"      # Audio target confirmed above acquisition threshold
    ORIENTING = "ORIENTING"              # Fast orienting saccade towards target bearing
    VISUAL_ACQUIRE = "VISUAL_ACQUIRE"    # Camera looking for face in expected bearing window
    TRACKING = "TRACKING"                # Face locked in camera FOV; smooth visual tracking
    HOLD = "HOLD"                        # Target paused or speech ceased; maintaining dwell gaze
    TARGET_LOST = "TARGET_LOST"          # Target absent; coasting last known state before timeout
    RETURNING = "RETURNING"              # Smoothly returning to neutral 0° center


class PrioritySource(str, Enum):
    """Priority arbitration source for head gaze authority."""
    SAFETY = "SAFETY"                    # Emergency stop or sleep lock (Highest priority)
    GESTURE = "GESTURE"                  # Scripted social gesture sequence (nod, shake, scan)
    DIALOGUE = "DIALOGUE"                # Direct dialogue gaze intent from cognitive brain
    ACTIVE_SPEAKER = "ACTIVE_SPEAKER"    # Multimodal active speaker tracking
    VISUAL_PERSON = "VISUAL_PERSON"      # Visual-only human presence in social zone
    IDLE = "IDLE"                        # Ambient baseline / idle return (Lowest priority)


@dataclass
class AudioObservation:
    """Raw acoustic directional observation from microphone array perception."""
    timestamp: float
    valid: bool
    vad: bool
    raw_azimuth_deg: float = 0.0          # Reported by array [0..359] clockwise
    relative_azimuth_deg: float = 0.0     # Head-relative bearing [-180..+180] REP-103
    body_azimuth_deg: float = 0.0         # Robot base coordinate bearing [-180..+180]
    elevation_deg: float = 0.0
    confidence: float = 0.0               # [0.0..1.0] from PSR and energy
    rms: float = 0.0                      # Frame acoustic energy RMS
    peak: float = 0.0                     # Peak amplitude
    snr_db: float = 0.0                   # Signal-to-noise ratio estimate


@dataclass
class FilteredAudioState:
    """Filtered acoustic state estimate with estimated angular velocity."""
    timestamp: float
    valid: bool
    azimuth_deg: float = 0.0              # Filtered body azimuth [-180..+180]
    angular_velocity_deg_s: float = 0.0   # Estimated angular rate (dθ/dt)
    confidence: float = 0.0               # Motion-compensated confidence [0.0..1.0]
    variance: float = 1.0                 # Kalman estimation variance
    is_outlier: bool = False              # True if sample was gated as an isolated outlier
    motion_attenuated: bool = False       # True if confidence was attenuated due to head motion


@dataclass
class VisualObservation:
    """Single-frame visual detection from camera (OAK-D Lite)."""
    timestamp: float
    valid: bool
    target_id: Optional[str] = None
    bbox: Tuple[int, int, int, int] = (0, 0, 0, 0)  # (x, y, w, h) in pixels
    u_norm: float = 0.0                   # Normalized image coordinates [-1.0..+1.0]
    v_norm: float = 0.0
    depth_m: float = 0.0                  # Metric stereo depth
    pos_3d_camera: Tuple[float, float, float] = (0.0, 0.0, 0.0)  # (x_opt, y_opt, z_opt) in meters
    camera_azimuth_deg: float = 0.0       # Angle relative to optical axis [-36°..+36°]
    camera_elevation_deg: float = 0.0
    body_azimuth_deg: float = 0.0         # Transformed to robot base coordinate frame
    confidence: float = 0.0               # Detection confidence [0.0..1.0]
    eyes_visible: bool = False            # True if facial landmarks / eyes confirmed
    eye_contact: bool = False             # True if looking directly at robot
    head_yaw_deg: float = 0.0             # User's estimated head pose yaw
    emotion: str = "neutral"              # Facial emotion
    person_name: Optional[str] = None     # Recognized name
    is_known: bool = False


@dataclass
class VisualTargetTrack:
    """Persistent 3D visual track with temporal Kalman filtering and coasting."""
    target_id: str
    pos_3d: Tuple[float, float, float]    # (x, y, z) in robot base frame
    vel_3d: Tuple[float, float, float]    # (vx, vy, vz) in m/s
    body_azimuth_deg: float
    body_elevation_deg: float
    distance_m: float
    confidence: float
    tracking_state: TrackingState
    last_seen_time: float
    age_frames: int = 1
    missed_frames: int = 0
    emotion: str = "neutral"
    person_name: Optional[str] = None
    is_known: bool = False
    eye_contact: bool = False


@dataclass
class FusedTarget:
    """Unified audio-visual target representation."""
    target_id: str
    modality: Modality
    body_azimuth_deg: float
    body_elevation_deg: float
    distance_m: float
    confidence: float
    is_speaking: bool
    eye_contact: bool
    person_name: Optional[str]
    is_known: bool
    timestamp: float
    tracking_state: TrackingState
    audio_confidence: float = 0.0
    visual_confidence: float = 0.0


@dataclass
class TargetState:
    """Complete target management state snapshot."""
    active_target: Optional[FusedTarget]
    candidate_targets: List[FusedTarget] = field(default_factory=list)
    timestamp: float = 0.0


@dataclass
class GazeCommand:
    """Authoritative output from Gaze Manager to Motion Planner."""
    target_yaw_deg: float
    target_pitch_deg: float = 0.0
    priority_source: PrioritySource = PrioritySource.IDLE
    gaze_state: GazeStateEnum = GazeStateEnum.IDLE
    active_target_id: Optional[str] = None
    confidence: float = 0.0
    timestamp: float = 0.0


@dataclass
class TrajectoryPoint:
    """Interpolated smooth motion setpoint for low-level controller."""
    timestamp: float
    position_deg: float
    velocity_deg_s: float = 0.0
    acceleration_deg_s2: float = 0.0
    jerk_deg_s3: float = 0.0
    is_settled: bool = False


@dataclass
class HeadFeedback:
    """Actual closed-loop telemetry feedback from hardware MCU."""
    timestamp: float
    actual_yaw_deg: float
    actual_velocity_deg_s: float = 0.0
    target_yaw_deg: float = 0.0
    encoder_ticks: int = 0
    motor_pwm: int = 0
    is_stalled: bool = False
    is_limited: bool = False
    watchdog_ok: bool = True
    mcu_alive: bool = True
