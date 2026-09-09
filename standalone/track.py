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

    Architecture:
        ReSpeaker (VOICEACTIVITY + DOAANGLE)
                    ↓
        circular filtering (atan2 mean, angle wrap-around safe)
                    ↓
        outlier rejection (single-spike rejection, 2-consecutive step change)
                    ↓
        calibrated DOA -> ASTRO head yaw (piecewise linear, bounded)
                    ↓
        deadband suppression (prevents servo jitter on minor fluctuations)
                    ↓
        target_yaw_deg -> head.send_angle()
    """

    # Physical calibration measurements on robot:
    # 1) Front 0°: DOA 69.0° -> Yaw 0.0°
    # 2) Left 45°: DOA 33.0° -> Yaw -45.0°
    # 3) Right 45°: DOA 142.0° -> Yaw +45.0°
    # 4) Right 90°: DOA 149.0° -> Yaw +90.0°
    CALIBRATION_POINTS = (
        (33.0, -45.0),
        (69.0, 0.0),
        (142.0, 45.0),
        (149.0, 90.0),
    )

    def __init__(
        self,
        hid=None,
        hold_timeout_s: float = 1.2,
        deadband_deg: float = 5.0,
        outlier_threshold_deg: float = 30.0,
        filter_window_size: int = 5,
    ):
        self.hid = hid
        self.hold_timeout_s = float(hold_timeout_s)
        self.deadband_deg = float(deadband_deg)
        self.outlier_threshold_deg = float(outlier_threshold_deg)
        self.filter_window_size = int(filter_window_size)

        self.filtered_doa: Optional[float] = None
        self._history: list[float] = []
        self._outlier_candidate: Optional[float] = None
        self._outlier_count: int = 0

        self.active_target_yaw: float = 0.0
        self._last_voice_activity_time: float = 0.0
        self._tracking_active: bool = False

        # Polling cache
        self._last_poll_time: float = 0.0
        self._cached_vad: Optional[bool] = None
        self._cached_doa: Optional[float] = None

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
    def calibrated_yaw(cls, doa_deg: float) -> float:
        """Monotonic piecewise linear calibration from ReSpeaker DOA to ASTRO Head Yaw.

        Measurements (physically measured on robot):
            DOA 33.0°  -> Yaw -45.0°
            DOA 69.0°  -> Yaw   0.0°
            DOA 142.0° -> Yaw +45.0°
            DOA 149.0° -> Yaw +90.0°

        Saturation:
            DOA outside [33.0, 149.0] saturates safely to the nearest calibrated endpoint:
            - Nearest to 33.0° -> -45.0° (e.g. 10.0°, 0.0°, 350.0°)
            - Nearest to 149.0° -> +90.0° (e.g. 180.0°, 250.0°)
        """
        raw = float(doa_deg) % 360.0
        if 33.0 <= raw <= 149.0:
            if raw <= 69.0:
                t = (raw - 33.0) / (69.0 - 33.0)
                return -45.0 + t * 45.0
            elif raw <= 142.0:
                t = (raw - 69.0) / (142.0 - 69.0)
                return 0.0 + t * 45.0
            else:  # 142.0 < raw <= 149.0
                t = (raw - 142.0) / (149.0 - 142.0)
                return 45.0 + t * 45.0

        dist_33 = cls.circular_dist(raw, 33.0)
        dist_149 = cls.circular_dist(raw, 149.0)
        return -45.0 if dist_33 <= dist_149 else 90.0

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

    def update(
        self,
        doa_raw: Optional[float],
        voice_activity: bool,
        timestamp: float,
    ) -> float:
        """Updates localizer state with new DOA and VAD readings."""
        if voice_activity:
            self._last_voice_activity_time = timestamp
            was_tracking = self._tracking_active
            self._tracking_active = True

            if doa_raw is not None:
                if not self.reject_outlier(doa_raw):
                    candidate = self.calibrated_yaw(self.filtered_doa)
                    if not was_tracking:
                        self.active_target_yaw = candidate
                    else:
                        self.apply_deadband(candidate)
        else:
            # VOICEACTIVITY is False: do NOT update target with incoming DOA
            if self._tracking_active:
                if timestamp - self._last_voice_activity_time > self.hold_timeout_s:
                    self._tracking_active = False
                    self.active_target_yaw = 0.0
                    self.reset_filter()

        return self.target_yaw_deg

    @property
    def target_yaw_deg(self) -> float:
        """Authoritative audio target yaw. Returns 0.0 when not tracking."""
        if not self._tracking_active:
            return 0.0
        return self.active_target_yaw

    def is_tracking(self, now: Optional[float] = None) -> bool:
        """Returns True if localizer is currently actively tracking speech."""
        if not self._tracking_active:
            return False
        if now is not None and (now - self._last_voice_activity_time > self.hold_timeout_s):
            self._tracking_active = False
            self.active_target_yaw = 0.0
            self.reset_filter()
            return False
        return True

    def reset_filter(self) -> None:
        """Clears circular filter history and outlier state."""
        self.filtered_doa = None
        self._history.clear()
        self._outlier_candidate = None
        self._outlier_count = 0

    def reset(self) -> None:
        """Full reset of localizer state."""
        self._tracking_active = False
        self.active_target_yaw = 0.0
        self._last_voice_activity_time = 0.0
        self.reset_filter()

    def on_vision_active(self) -> None:
        """Called when visual tracking is active; immediately drops audio tracking."""
        self.reset()

    def read_voice_activity(self) -> Optional[bool]:
        """Reads hardware VOICEACTIVITY from ReSpeaker XVF3000 (module 19, offset 32)."""
        if self.hid is None:
            return None
        if hasattr(self.hid, "voice_activity") and callable(self.hid.voice_activity):
            return self.hid.voice_activity()
        if hasattr(self.hid, "_read_param") and callable(self.hid._read_param):
            val = self.hid._read_param(19, 32)
            return bool(val) if val in (0, 1) else None
        return None

    def read_doa_angle(self) -> Optional[float]:
        """Reads hardware DOAANGLE from ReSpeaker XVF3000 (module 21, offset 0)."""
        if self.hid is None:
            return None
        if hasattr(self.hid, "doa_angle") and callable(self.hid.doa_angle):
            return self.hid.doa_angle()
        if hasattr(self.hid, "_read_param") and callable(self.hid._read_param):
            val = self.hid._read_param(21, 0)
            return float(val) if val is not None and 0 <= val <= 359 else None
        return None

    def read_and_update(
        self,
        now: float,
        fallback_doa: Optional[float] = None,
        fallback_vad: bool = False,
        poll_interval_s: float = 0.05,
    ) -> float:
        """Polls ReSpeaker hardware registers and updates localizer."""
        if self.hid is not None:
            if now - self._last_poll_time >= poll_interval_s or self._last_poll_time == 0.0:
                self._cached_vad = self.read_voice_activity()
                self._cached_doa = self.read_doa_angle()
                self._last_poll_time = now

        vad = self._cached_vad if self._cached_vad is not None else fallback_vad
        doa = self._cached_doa if self._cached_doa is not None else fallback_doa

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
    parser.add_argument("--audio-hold-grace", type=float, default=1.2,
                        help="Audio hedefinin konuşma kesildikten sonra tutulacağı süre (saniye, varsayılan: 1.2)")
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

            doa_deg = audio.latest_doa_deg(now) if audio.available else None
            speech = audio.latest_speech(now) if audio.available else None

            # ReSpeaker XVF3000 DSP (VOICEACTIVITY + DOAANGLE) localizer update:
            localizer.read_and_update(
                now=now,
                fallback_doa=doa_deg,
                fallback_vad=speech.is_speech if speech else False,
            )

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
            # Vision önceliği: Görüntü yüz tespit ettiğinde audio derhal bırakılır.
            if result.owner == PrioritySource.VISUAL_TRACKING or len(detections) > 0:
                localizer.on_vision_active()
                target_yaw = result.target_yaw_deg
            elif localizer.is_tracking(now):
                target_yaw = localizer.target_yaw_deg
                result.target_yaw_deg = target_yaw
                result.owner = PrioritySource.ACTIVE_SPEAKER
                result.gaze_state = GazeStateEnum.ORIENTING
                result.target_id = "audio_speaker_1"
            else:
                target_yaw = 0.0
                result.target_yaw_deg = 0.0
                result.owner = PrioritySource.IDLE
                result.gaze_state = GazeStateEnum.IDLE
                result.target_id = None

            head.send_angle(target_yaw)
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
                doa_deg=localizer.filtered_doa if localizer.is_tracking() else doa_deg,
                head_feedback=head.has_feedback,
                speech=speech,
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
