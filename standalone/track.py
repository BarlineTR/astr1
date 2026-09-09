#!/usr/bin/env python3
"""ASTRO — ROS'suz yüz ve ses takibi.

Kamerayı, mikrofonu ve Arduino'yu doğrudan açar; aradaki bütün karar mantığı
ROS düğümünün kullandığı nesnelerin ta kendisidir (astro_base.gaze). Tek fark
taşıma katmanının olmaması: DDS yok, topic yok, launch yok, tek process.

    ./.venv/bin/python standalone/track.py
    ./.venv/bin/python standalone/track.py --serial /dev/ttyACM0
    ./.venv/bin/python standalone/track.py --no-window --seconds 30

Ekrandaki şerit üç katmanı yan yana gösterir; bir sorunun hangisinde olduğunu
tahmin etmeden okumak için:

    kutu yok                       -> algılama
    kutu var ama owner=IDLE        -> arbitrasyon
    istenen değişiyor, gerçek değil -> aktüatör
"""

import argparse
import math
import sys
import time
from pathlib import Path
from typing import Optional, Sequence

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parent))

import core_path  # noqa: F401,E402
from astro_audio.respeaker_usb import ReSpeakerHID  # noqa: E402
from astro_audio.speech_detector import SpeechVerdict  # noqa: E402
from head_link import HeadLink, open_port  # noqa: E402
from recorder import OverlayRecorder, default_path  # noqa: E402
from sources import AudioSource, CameraSource  # noqa: E402
from astro_base.gaze.types import GazeStateEnum, PrioritySource  # noqa: E402
from stereo_doa import DEFAULT_MIC_SPACING_M  # noqa: E402
from statuslog import StatusLog  # noqa: E402
from tracker import GazeTracker  # noqa: E402

BOX_COLOUR = (0, 215, 255)
TEXT_COLOUR = (0, 255, 120)


class ReSpeakerAudioLocalizer:
    """ReSpeaker XVF3000 DSP (VOICEACTIVITY + DOAANGLE) -> ASTRO Head Yaw Localizer.

    Sector-based architecture (V2):
        ReSpeaker (VOICEACTIVITY + DOAANGLE)
                    ↓
        DOA -> 3 sector mapping (LEFT / CENTER / RIGHT)
                    ↓
        sector confirmation (N consecutive readings to switch)
                    ↓
        sector -> coarse target yaw (-45° / 0° / +45°)
                    ↓
        target_yaw_deg -> head.send_angle()

    Why sectors instead of continuous angles:
        ReSpeaker XVF3000 DOA output is unreliable for precise angular mapping.
        Live testing showed DOA ~148° (calibrated RIGHT 83°) when the user was
        physically in FRONT (visual confirmed ~-10° to +27°). The previous
        piecewise linear calibration amplified DOA noise into 80°+ wrong-direction
        turns. Sectors limit the worst-case error to ~45° and let visual tracking
        refine the final heading.
    """

    # ── Sector boundaries ──────────────────────────────────────────
    # DOA ranges for the front operating hemisphere [20°, 155°].
    # Generous margins prevent jitter at boundaries.
    VALID_DOA_MIN = 20.0
    VALID_DOA_MAX = 155.0

    SECTOR_LEFT_MAX = 55.0     # DOA < 55° = LEFT
    SECTOR_RIGHT_MIN = 100.0   # DOA >= 100° = RIGHT
    #                            55°..100° = CENTER

    SECTOR_TARGETS = {"LEFT": 60.0, "CENTER": 0.0, "RIGHT": -60.0}
    # NOTE: LEFT/RIGHT targets are SWAPPED from the original calibration labels.
    # Live testing proved calibration labels were from user's perspective (facing robot):
    #   DOA ~32  ("LEFT" in calib)  = robot's physical RIGHT  → motor +60°
    #   DOA ~148 ("RIGHT" in calib) = robot's physical LEFT   → motor -60°
    # Evidence: visual tracking found user at -70.2° when DOA read 148;
    # +-60° puts both 45° and 70°-80° speakers squarely inside the camera FOV (69°).
    SECTOR_CONFIRM_COUNT = 2   # consecutive readings to switch sector while tracking

    # ── Legacy calibration (kept for backward-compat tests) ────────
    CALIBRATION_POINTS = (
        (25.0, -90.0),
        (32.0, -45.0),
        (78.0, 0.0),
        (142.0, 45.0),
        (149.0, 90.0),
    )

    def __init__(
        self,
        hid=None,
        hold_timeout_s: float = 5.0,
        deadband_deg: float = 5.0,
        outlier_threshold_deg: float = 30.0,
        filter_window_size: int = 5,
    ):
        self.hid = hid
        self.hold_timeout_s = float(hold_timeout_s)
        # Legacy params kept for CLI compat; unused in sector mode.
        self.deadband_deg = float(deadband_deg)
        self.outlier_threshold_deg = float(outlier_threshold_deg)
        self.filter_window_size = int(filter_window_size)

        # Sector state
        self._confirmed_sector: Optional[str] = None
        self._pending_sector: Optional[str] = None
        self._pending_count: int = 0

        # Target
        self.active_target_yaw: float = 0.0
        self._last_voice_activity_time: float = 0.0
        self._last_valid_target_time: float = 0.0
        self._tracking_active: bool = False

        # Diagnostics / logging
        self.last_raw_doa: Optional[float] = None

        # Polling cache
        self._last_poll_time: float = 0.0
        self._cached_vad: Optional[bool] = None
        self._cached_doa: Optional[float] = None
        self._vad_warning_emitted: bool = False
        self._last_vad_warning_time: float = 0.0

        # Legacy filter state (kept for backward-compat static methods/tests)
        self.filtered_doa: Optional[float] = None
        self._history: list[float] = []
        self._outlier_candidate: Optional[float] = None
        self._outlier_count: int = 0

    @staticmethod
    def circular_dist(a: float, b: float) -> float:
        """Angular distance between two angles in degrees [0, 180]."""
        diff = (float(a) - float(b) + 180.0) % 360.0 - 180.0
        return abs(diff)

    @staticmethod
    def circular_mean(angles: Sequence[float]) -> float:
        """Circular mean of angles in degrees, properly handling wrap-around."""
        if not angles:
            return 0.0
        s = sum(math.sin(math.radians(float(a))) for a in angles)
        c = sum(math.cos(math.radians(float(a))) for a in angles)
        if abs(s) < 1e-9 and abs(c) < 1e-9:
            return float(angles[-1]) % 360.0
        return math.degrees(math.atan2(s, c)) % 360.0

    @classmethod
    def is_valid_doa(cls, doa_deg: Optional[float]) -> bool:
        """Returns True if doa_deg is within the valid front operating workspace.

        Rear and ambiguous DOA regions (e.g. ~285-330°, 155-360°, 0-20°) are invalid.
        """
        if doa_deg is None:
            return False
        raw = float(doa_deg) % 360.0
        return cls.VALID_DOA_MIN <= raw <= cls.VALID_DOA_MAX

    @classmethod
    def doa_to_sector(cls, doa_deg: float) -> Optional[str]:
        """Maps a raw DOA reading to a coarse sector.

        Returns:
            "LEFT", "CENTER", or "RIGHT" for valid DOA in front hemisphere.
            None for rear / invalid DOA.
        """
        raw = float(doa_deg) % 360.0
        if not cls.is_valid_doa(raw):
            return None
        if raw < cls.SECTOR_LEFT_MAX:
            return "LEFT"
        elif raw >= cls.SECTOR_RIGHT_MIN:
            return "RIGHT"
        else:
            return "CENTER"

    @property
    def confirmed_sector(self) -> Optional[str]:
        """Currently confirmed sector, or None if not tracking."""
        return self._confirmed_sector if self._tracking_active else None

    @classmethod
    def calibrated_yaw(cls, doa_deg: float) -> Optional[float]:
        """Monotonic piecewise linear calibration from ReSpeaker DOA to ASTRO Head Yaw.

        Operating workspace:
            LEFT <= 90° (yaw >= -90.0°)
            FRONT = 0° (yaw = 0.0°)
            RIGHT <= 90° (yaw <= +90.0°)

        Physical calibration measurements on robot:
            DOA 32.0°  -> Yaw -45.0°
            DOA 78.0°  -> Yaw   0.0°
            DOA 142.0° -> Yaw +45.0°
            DOA 149.0° -> Yaw +90.0°

        Saturation within valid workspace [20.0°, 155.0°]:
            DOA 20.0°..25.0°   -> -90.0°
            DOA 25.0°..32.0°   -> -90.0°..-45.0° interpolation
            DOA 32.0°..78.0°   -> -45.0°..0.0° interpolation
            DOA 78.0°..142.0°  -> 0.0°..+45.0° interpolation
            DOA 142.0°..149.0° -> +45.0°..+90.0° interpolation
            DOA 149.0°..155.0° -> +90.0°

        Returns:
            Calibrated yaw in [-90.0°, +90.0°], or None if DOA is in the rear/invalid region.
        """
        raw = float(doa_deg) % 360.0
        if not cls.is_valid_doa(raw):
            return None

        if raw <= 25.0:
            return -90.0
        elif raw <= 32.0:
            t = (raw - 25.0) / (32.0 - 25.0)
            return -90.0 + t * 45.0
        elif raw <= 78.0:
            t = (raw - 32.0) / (78.0 - 32.0)
            return -45.0 + t * 45.0
        elif raw <= 142.0:
            t = (raw - 78.0) / (142.0 - 78.0)
            return 0.0 + t * 45.0
        elif raw <= 149.0:
            t = (raw - 142.0) / (149.0 - 142.0)
            return 45.0 + t * 45.0
        else:  # 149.0 < raw <= 155.0
            return 90.0

    def reject_outlier(self, raw_doa: float) -> bool:
        """Rejects single transient spikes in DOA angle.

        Returns True if raw_doa is rejected as an outlier, False if accepted.
        If 2 consecutive samples are at the new angle, it is accepted as a step change.
        """
        raw = float(raw_doa) % 360.0
        if self.filtered_doa is None:
            self.filtered_doa = raw
            self._history = [raw]
            self._outlier_candidate = None
            self._outlier_count = 0
            return False

        dist = self.circular_dist(raw, self.filtered_doa)
        if dist <= self.outlier_threshold_deg:
            self._outlier_candidate = None
            self._outlier_count = 0
            self._history.append(raw)
            if len(self._history) > self.filter_window_size:
                self._history.pop(0)
            self.filtered_doa = self.circular_mean(self._history)
            return False

        # dist > outlier_threshold_deg
        if (
            self._outlier_candidate is not None
            and self.circular_dist(raw, self._outlier_candidate) <= self.outlier_threshold_deg
        ):
            # 2nd consecutive sample at new angle -> accept step change
            self.filtered_doa = raw
            self._history = [raw]
            self._outlier_candidate = None
            self._outlier_count = 0
            return False

        self._outlier_candidate = raw
        self._outlier_count = 1
        return True

    def apply_deadband(self, candidate_yaw: float) -> float:
        """Applies deadband to prevent servo jitter on small yaw changes."""
        if abs(candidate_yaw - self.active_target_yaw) >= self.deadband_deg:
            self.active_target_yaw = candidate_yaw
        return self.active_target_yaw

    def target_yaw(self, candidate_yaw: float) -> float:
        """Alias for apply_deadband."""
        return self.apply_deadband(candidate_yaw)

    # ── Tracking state update ─────────────────────────────────────────

    def update(
        self,
        doa_raw: Optional[float],
        voice_activity: bool,
        timestamp: float,
    ) -> float:
        """Updates localizer state with new DOA and VAD readings.

        Sector-based logic:
        1. When idle (or first detection ever) → immediately accept sector (fast response)
        2. While actively tracking, switching to a different sector requires
           SECTOR_CONFIRM_COUNT consecutive readings (prevents phantom noise flip)
        3. Within a sector, target stays at sector target (no jitter)
        """
        is_valid = self.is_valid_doa(doa_raw)

        if voice_activity and is_valid:
            assert doa_raw is not None
            self.last_raw_doa = float(doa_raw)
            self._last_voice_activity_time = timestamp
            self._last_valid_target_time = timestamp
            was_tracking = self._tracking_active
            self._tracking_active = True

            sector = self.doa_to_sector(doa_raw)
            if sector is not None:
                if not was_tracking or self._confirmed_sector is None:
                    # Idle or first detection → accept immediately to react fast
                    self._confirmed_sector = sector
                    self._pending_sector = None
                    self._pending_count = 0
                    self.active_target_yaw = self.SECTOR_TARGETS[sector]
                elif sector == self._confirmed_sector:
                    # Same sector → refresh/reinforce, restore target, clear pending
                    self.active_target_yaw = self.SECTOR_TARGETS[sector]
                    self._pending_sector = None
                    self._pending_count = 0
                elif sector == self._pending_sector:
                    # Consecutive reading in different sector while actively tracking → count up
                    self._pending_count += 1
                    if self._pending_count >= self.SECTOR_CONFIRM_COUNT:
                        self._confirmed_sector = sector
                        self.active_target_yaw = self.SECTOR_TARGETS[sector]
                        self._pending_sector = None
                        self._pending_count = 0
                else:
                    # New pending sector
                    self._pending_sector = sector
                    self._pending_count = 1

        elif voice_activity and not is_valid:
            # VAD true but DOA is rear/invalid: hold current target, don't generate rear target
            if self._tracking_active:
                if timestamp - self._last_valid_target_time > self.hold_timeout_s:
                    self._tracking_active = False
                    self.active_target_yaw = 0.0
                    # Keep _confirmed_sector so phantom DOA after timeout needs confirmation
                    self._pending_sector = None
                    self._pending_count = 0
        else:
            # VOICEACTIVITY is False: hold current target for grace period
            if self._tracking_active:
                if timestamp - self._last_valid_target_time > self.hold_timeout_s:
                    self._tracking_active = False
                    self.active_target_yaw = 0.0
                    # Keep _confirmed_sector so phantom DOA after timeout needs confirmation
                    self._pending_sector = None
                    self._pending_count = 0

        return self.target_yaw_deg

    @property
    def target_yaw_deg(self) -> float:
        """Authoritative audio target yaw. Returns 0.0 when not tracking."""
        if not self._tracking_active:
            return 0.0
        return self.active_target_yaw

    @property
    def motor_yaw_deg(self) -> float:
        """Motor command yaw matching target_yaw_deg."""
        return self.target_yaw_deg

    def is_tracking(self, now: Optional[float] = None) -> bool:
        """Returns True if localizer is currently actively tracking speech."""
        if not self._tracking_active:
            return False
        if now is not None and (now - self._last_valid_target_time > self.hold_timeout_s):
            self._tracking_active = False
            self.active_target_yaw = 0.0
            self._pending_sector = None
            self._pending_count = 0
            return False
        return True

    def _clear_sector_state(self) -> None:
        """Clears sector confirmation state."""
        self._confirmed_sector = None
        self._pending_sector = None
        self._pending_count = 0

    def reset_filter(self) -> None:
        """Clears circular filter history and outlier state (legacy compat)."""
        self.filtered_doa = None
        self._history.clear()
        self._outlier_candidate = None
        self._outlier_count = 0

    def reset(self) -> None:
        """Full reset of localizer state."""
        self._tracking_active = False
        self.active_target_yaw = 0.0
        self._last_voice_activity_time = 0.0
        self._last_valid_target_time = 0.0
        self._clear_sector_state()
        self.last_raw_doa = None
        self.reset_filter()

    def on_vision_active(self) -> None:
        """Called when visual tracking is active; immediately drops audio tracking."""
        self.reset()

    def read_voice_activity(self) -> Optional[bool]:
        """Reads hardware VAD from ReSpeaker XVF3000.

        Uses public ReSpeakerHID methods:
        - voice_activity() if defined
        - speech_detected() from respeaker_usb.py
        Does NOT touch private _read_param.
        """
        if self.hid is None:
            return None
        if hasattr(self.hid, "voice_activity") and callable(self.hid.voice_activity):
            val = self.hid.voice_activity()
            return bool(val) if val is not None else None
        if hasattr(self.hid, "speech_detected") and callable(self.hid.speech_detected):
            val = self.hid.speech_detected()
            return bool(val) if val is not None else None
        return None

    def read_doa_angle(self) -> Optional[float]:
        """Reads hardware DOA angle from ReSpeaker XVF3000.

        Uses public ReSpeakerHID method:
        - doa_angle()
        Does NOT touch private _read_param.
        """
        if self.hid is None:
            return None
        if hasattr(self.hid, "doa_angle") and callable(self.hid.doa_angle):
            val = self.hid.doa_angle()
            return float(val) if val is not None and 0 <= val <= 359 else None
        return None

    def read_and_update(
        self,
        now: float,
        poll_interval_s: float = 0.05,
    ) -> float:
        """Polls ReSpeaker hardware registers and updates localizer.

        Authoritative VAD and DOA come strictly from hardware.
        If hardware VAD cannot be read, tracking is disabled and a warning is logged.
        No software VAD fallback is used for audio tracking.
        """
        if self.hid is not None:
            if now - self._last_poll_time >= poll_interval_s or self._last_poll_time == 0.0:
                self._cached_vad = self.read_voice_activity()
                self._cached_doa = self.read_doa_angle()
                self._last_poll_time = now

        if self._cached_vad is None:
            if not self._vad_warning_emitted or (now - self._last_vad_warning_time > 5.0):
                print("⚠️  ReSpeaker Hardware VAD okunamıyor (donanım yok veya yanıt vermiyor) — ses takibi devre dışı")
                self._vad_warning_emitted = True
                self._last_vad_warning_time = now
            self.reset()
            return 0.0

        vad = bool(self._cached_vad)
        doa = self._cached_doa

        return self.update(doa_raw=doa, voice_activity=vad, timestamp=now)


def draw_overlay(frame, detections, result, fps: float, audio_ok: bool, head_ok: bool,
                 fixed_head: bool = False):
    """Boxes, plus the two lines that say which layer is speaking."""
    for det in detections:
        cv2.rectangle(frame, (det.x, det.y), (det.x + det.w, det.y + det.h), BOX_COLOUR, 2)
        cv2.putText(frame, f"{det.confidence:.2f}", (det.x, max(18, det.y - 8)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, BOX_COLOUR, 1, cv2.LINE_AA)

    height, width = frame.shape[:2]
    band = 60
    cv2.rectangle(frame, (0, height - band), (width, height), (0, 0, 0), -1)
    pose_label = "sabit" if fixed_head else "gercek" if head_ok else "tahmin"
    lines = (
        f"{result.gaze_state.value}  owner={result.owner.value}  "
        f"hedef={result.target_id or '-'}  conf={result.confidence:.2f}",
        f"istenen {result.target_yaw_deg:+.1f}  ->  {pose_label} {result.head_angle_deg:+.1f}"
        f"   [{fps:.0f} fps  ses:{'V' if audio_ok else 'X'}  kafa:{'V' if head_ok else 'X'}]",
    )
    for i, text in enumerate(lines):
        cv2.putText(frame, text, (8, height - band + 24 + i * 26),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.52, TEXT_COLOUR, 1, cv2.LINE_AA)
    return frame


def main(argv=None, hid=None) -> int:
    parser = argparse.ArgumentParser(description="ROS'suz ASTRO yüz/ses takibi")
    parser.add_argument("--camera", type=int, default=0, help="Kamera indeksi")
    head_mode = parser.add_mutually_exclusive_group()
    head_mode.add_argument("--serial", default=None, help="Arduino portu, örn. /dev/ttyACM0")
    head_mode.add_argument("--fixed-head", action="store_true",
                           help="Sabit dizüstü kamera/mikrofon teşhisi: kafa referansı "
                                "0° kalır; motor bağlantısıyla birlikte kullanılmaz")
    parser.add_argument("--audio-device", type=int, default=None, help="Mikrofon indeksi")
    parser.add_argument("--mic-channels", type=str, default=None, metavar="A,B,C,D",
                        help="Dizide hangi kanalların (ön,sağ,arka,sol) mikrofon "
                             "olduğu. 6 kanallı USB diziler için varsayılan 1,2,3,4; "
                             "doğru sırayı audio_check.py ölçer.")
    parser.add_argument("--mic-spacing", type=float, default=DEFAULT_MIC_SPACING_M,
                        metavar="M",
                        help="Stereo modda iki mikrofon arası mesafe (metre). Açının "
                             "ölçeğini belirler; işaret ve sıralama bundan bağımsız "
                             f"doğrudur. Varsayılan {DEFAULT_MIC_SPACING_M} m.")
    parser.add_argument("--no-window", action="store_true", help="Pencere açma")
    parser.add_argument("--no-voice", action="store_true",
                        help="Sesli yanıtı kapat (yalnızca takip)")
    parser.add_argument("--seconds", type=float, default=None, help="Süre sınırı")
    parser.add_argument("--speech-harmonicity", type=float, default=0.20,
                        help="Konuşma tespiti için minimum harmoniklik eşiği (varsayılan: 0.20)")
    parser.add_argument("--speech-modulation", type=float, default=0.08,
                        help="Konuşma tespiti için minimum hece modülasyonu eşiği (varsayılan: 0.08)")
    parser.add_argument("--log-interval", type=float, default=1.0, metavar="SN",
                        help="Terminale durum satiri basma araligi (0 = yalnizca "
                             "durum/hedef degisimlerinde bas)")
    parser.add_argument("--audio-hold-grace", type=float, default=5.0,
                        help="Audio hedefinin konuşma kesildikten sonra tutulacağı süre (saniye, varsayılan: 5.0)")
    parser.add_argument("--audio-deadband", type=float, default=5.0,
                        help="Audio hedefi deadband eşiği (derece, varsayılan: 5.0)")
    parser.add_argument("--record", nargs="?", const="", default=None, metavar="DOSYA",
                        help="Bindirilmiş görüntüyü videoya kaydet. Yol verilmezse "
                             "astro_<tarih>.mp4 kullanılır. Ekransız çalışırken "
                             "(--no-window) neyin takip edildiğini sonradan izlemek için.")
    opts = parser.parse_args(argv)

    head = HeadLink(port=open_port(opts.serial) if opts.serial else None)
    if opts.fixed_head:
        print("🔌 Sabit kamera/mikrofon teşhisi — kafa referansı 0°, encoder ölçümü yok")
    else:
        print("🔌 Arduino bağlı" if head.connected
              else "🔌 Arduino yok — açık çevrim, kafa açısı tahmin edilecek")

    camera = CameraSource(device=opts.camera)
    if not camera.available:
        print(f"❌ Kamera {opts.camera} açılamadı.")
        if camera.error:
            print(f"   OAK-D: {camera.error}")
        return 1
    if camera.backend == "webcam":
        print(f"📷 Webcam {opts.camera} (OAK-D yok) | yüz algılama: {camera.detector_name}")
    else:
        print(f"📷 {camera.backend} | yüz algılama: {camera.detector_name}")

    mic_channels = ([int(c) for c in opts.mic_channels.split(",")]
                    if opts.mic_channels else None)
    audio = AudioSource(
        device=opts.audio_device,
        mic_spacing_m=opts.mic_spacing,
        mic_channels=mic_channels,
        min_harmonicity=opts.speech_harmonicity,
        min_modulation=opts.speech_modulation,
    )
    audio.start()
    if not audio.available:
        print(f"🎤 Ses yok ({audio.error}) — yalnızca görüntüyle takip")
    elif audio.mode == "array":
        used = ",".join(str(c) for c in (audio._mic_channels or ()))
        print(f"🎤 4'lü mikrofon dizisi: {audio.device_name} — kanal {used} "
              f"(sıralama şüpheliyse: python standalone/audio_check.py)")
    else:
        print(f"🎤 Stereo çift: {audio.device_name} @{audio.sample_rate} Hz — "
              f"tek eksende yön (sağ/sol), ön/arka ayrımı yok")
    audio_was_available = audio.available

    voice_loop = None
    if not opts.no_voice and audio.available:
        # İçeride ve şart arkasında: `voice` `scipy`'yi (opsiyonel, bkz.
        # voice.py review R2) ve `astro_ai`'yi içe aktarıyor -- `--no-voice`
        # ile ya da ses donanımı yokken bunlar hiç gerekmemeli. Modül
        # seviyesinde koşulsuz import, README'nin vaat ettiği görüntü-yalnız
        # yolu (ses hiç kurulu olmasa da) bir bağımlılık eksikse çökertirdi.
        import voice as voice_module

        voice_loop = voice_module.build_default_loop(audio)
        if voice_loop is None:
            print(f"🗣️  {voice_module.LAST_SETUP_ERROR}")
        else:
            print(f"🗣️  Sesli yanıt açık — uyandırma sözcüğü: '{voice_loop.wake_word}'")

    recorder = None
    if opts.record is not None:
        recorder = OverlayRecorder(opts.record or default_path())
        print(f"🎬 Kayıt: {recorder.path}")

    status = StatusLog(interval_s=opts.log_interval)
    tracker = GazeTracker()
    respeaker_hid = hid if hid is not None else ReSpeakerHID()
    localizer = ReSpeakerAudioLocalizer(
        hid=respeaker_hid,
        hold_timeout_s=opts.audio_hold_grace,
        deadband_deg=opts.audio_deadband,
    )
    started = time.monotonic()
    frames, fps, last_fps_at, last_fps_frames = 0, 0.0, started, 0
    last_audio_log_yaw: Optional[float] = None

    try:
        while True:
            now = time.monotonic()
            if opts.seconds is not None and (now - started) >= opts.seconds:
                break

            ok, frame = camera.read()
            if not ok:
                print("⚠️  Kameradan kare gelmiyor")
                break

            detections = camera.detect(frame)
            head.poll()

            if audio_was_available and not audio.available:
                # The array check runs on the audio thread and can only fail once the
                # first blocks arrive, after the startup line was already printed.
                print(f"🎤 {audio.error} — yalnızca görüntüyle takip")
                audio_was_available = False

            # ReSpeaker XVF3000 DSP (VOICEACTIVITY + DOAANGLE) localizer update:
            # Audio target üretiminde AudioSource kullanılmaz; tek ve authoritative kaynak ReSpeakerAudioLocalizer'dır.
            localizer.read_and_update(now=now)

            if voice_loop is not None:
                voice_loop.pump(now)

            # Masadaki sensörler komutla dönmez. Bu modda bilinen sabit
            # referansı ortak beyne veririz; encoder varmış gibi raporlamayız.
            head_reference = (0.0 if opts.fixed_head else
                              head.measured_angle_deg if head.has_feedback else None)

            # GazeTracker.step() çağrısına DOA beslenmez (doa_deg=None).
            # Böylece eski continuous tracker DOA açılarının (-21.2, -36.9, -59.4 vb.)
            # üretilmesi ve dışarı sızması %100 engellenir.
            result = tracker.step(
                faces=detections,
                frame_size=(frame.shape[1], frame.shape[0]),
                doa_deg=None,
                speech=None,
                measured_head_deg=head_reference,
                timestamp=now,
                is_robot_speaking=voice_loop.is_speaking_at(now) if voice_loop else False,
            )

            # Audio target'ın tek ve authoritative kaynağı ReSpeakerAudioLocalizer'dır.
            # Vision önceliği: Görsel takip bir yüze kilitlendiğinde audio bırakılır.
            if result.owner == PrioritySource.VISUAL_TRACKING:
                localizer.on_vision_active()
                target_yaw = result.target_yaw_deg
                motor_yaw = target_yaw
                last_audio_log_yaw = None
            elif localizer.is_tracking(now):
                target_yaw = localizer.target_yaw_deg
                motor_yaw = target_yaw
                result.target_yaw_deg = target_yaw
                result.owner = PrioritySource.ACTIVE_SPEAKER
                result.gaze_state = GazeStateEnum.ORIENTING
                result.target_id = "audio_speaker_1"
                if last_audio_log_yaw != motor_yaw:
                    doa_str = f"{localizer.last_raw_doa:.0f}" if localizer.last_raw_doa is not None else "?"
                    sector_str = localizer.confirmed_sector or "?"
                    print(f"AUDIO sector={sector_str} DOA={doa_str} target={target_yaw:+.1f}")
                    last_audio_log_yaw = motor_yaw
            else:
                target_yaw = 0.0
                motor_yaw = 0.0
                result.target_yaw_deg = 0.0
                result.owner = PrioritySource.IDLE
                result.gaze_state = GazeStateEnum.IDLE
                result.target_id = None
                last_audio_log_yaw = None

            head.send_angle(motor_yaw)
            head.tick(now)

            frames += 1
            if now - last_fps_at >= 1.0:
                fps = (frames - last_fps_frames) / (now - last_fps_at)
                last_fps_at, last_fps_frames = now, frames

            status.update(
                elapsed_s=now - started,
                result=result,
                fps=fps,
                detections=len(detections),
                doa_deg=localizer.last_raw_doa if localizer.is_tracking() else None,
                head_feedback=head.has_feedback,
                speech=audio.latest_speech(now) if audio.available else None,
                fixed_head=opts.fixed_head,
            )

            # Bindirme bir kez çizilir: pencere ve kayıt aynı kareyi paylaşır.
            # İki kez çizmek, zaten takılan makinede kare başına maliyeti ikiye katlar.
            if recorder is not None or not opts.no_window:
                overlaid = draw_overlay(frame, detections, result, fps,
                                        audio.available, head.has_feedback, opts.fixed_head)
                if recorder is not None:
                    recorder.add(overlaid, now)
                if not opts.no_window:
                    cv2.imshow("ASTRO — ROS'suz takip", overlaid)
                    if cv2.waitKey(1) & 0xFF in (ord("q"), 27):
                        break
    except KeyboardInterrupt:
        pass
    finally:
        elapsed = max(time.monotonic() - started, 1e-6)
        print("\n" + status.summary(elapsed, frames))
        if tracker.head_feedback_missing:
            print("⚠️  Encoder hiç konuşmadı: kafa açısı komuttan tahmin edildi. "
                  "Gerçek açı sapabilir; --serial ile bağlayıp doğrulayın.")
        if recorder is not None:
            print(recorder.close())
        if voice_loop is not None:
            voice_loop.stop()
        camera.close()
        audio.close()
        head.close()
        if not opts.no_window:
            cv2.destroyAllWindows()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
