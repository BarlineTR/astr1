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
import sys
import time
from pathlib import Path
from typing import Optional, Sequence

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parent))

import core_path  # noqa: F401,E402
from head_link import HeadLink, open_port  # noqa: E402
from recorder import OverlayRecorder, default_path  # noqa: E402
from sources import AudioSource, CameraSource  # noqa: E402
from astro_base.gaze.types import PrioritySource  # noqa: E402
from stereo_doa import DEFAULT_MIC_SPACING_M  # noqa: E402
from statuslog import StatusLog  # noqa: E402
from tracker import GazeTracker  # noqa: E402

BOX_COLOUR = (0, 215, 255)
TEXT_COLOUR = (0, 255, 120)


class AudioSectorMapper:
    """Raw HID DOA -> Sektörel Kafa Yönelimi (-55°, 0°, +55°).

    Raw HID DOA aralıkları:
      0..55    -> LEFT   = -55°
      55..95   -> CENTER = 0°
      95..300  -> RIGHT  = +55°
      300..360 -> LEFT   = -55°

    Yeni sektöre geçiş için 3 ardışık aynı sektör örneği şartı.
    Sektör kararlı kaldığı sürece target_yaw sabit kalır.
    """

    SECTOR_LEFT = -55.0
    SECTOR_CENTER = 0.0
    SECTOR_RIGHT = 55.0

    def __init__(self, persistence_required: int = 3, timeout_s: float = 1.5):
        self.persistence_required = persistence_required
        self.timeout_s = timeout_s
        self.active_sector = None
        self._candidate_sector = None
        self._candidate_hits = 0
        self._last_raw_doa = None
        self._last_time = 0.0

    @staticmethod
    def classify_sector(raw_doa: float) -> float:
        raw = float(raw_doa) % 360.0
        if 0.0 <= raw <= 55.0 or 300.0 <= raw <= 360.0:
            return AudioSectorMapper.SECTOR_LEFT
        elif 55.0 < raw <= 95.0:
            return AudioSectorMapper.SECTOR_CENTER
        else:  # 95.0 < raw < 300.0
            return AudioSectorMapper.SECTOR_RIGHT

    def update(self, raw_doa, is_speech: bool, timestamp: float):
        if timestamp - self._last_time > self.timeout_s:
            self._candidate_sector = None
            self._candidate_hits = 0

        if raw_doa is None or not is_speech:
            return self.active_sector

        # Sadece yeni bir DOA değeri geldiğinde persistence sayacını işlet
        if self._last_raw_doa is not None and abs(raw_doa - self._last_raw_doa) < 1e-4:
            self._last_time = timestamp
            return self.active_sector

        self._last_raw_doa = raw_doa
        self._last_time = timestamp

        target = self.classify_sector(raw_doa)

        if self.active_sector is None:
            if target == self._candidate_sector:
                self._candidate_hits += 1
            else:
                self._candidate_sector = target
                self._candidate_hits = 1

            if self._candidate_hits >= self.persistence_required:
                self.active_sector = target
                self._candidate_sector = None
                self._candidate_hits = 0
        else:
            if target != self.active_sector:
                if target == self._candidate_sector:
                    self._candidate_hits += 1
                else:
                    self._candidate_sector = target
                    self._candidate_hits = 1

                if self._candidate_hits >= self.persistence_required:
                    self.active_sector = target
                    self._candidate_sector = None
                    self._candidate_hits = 0
            else:
                self._candidate_sector = None
                self._candidate_hits = 0

        return self.active_sector

    def reset(self):
        self.active_sector = None
        self._candidate_sector = None
        self._candidate_hits = 0
        self._last_raw_doa = None
        self._last_time = 0.0


class AudioTargetRetention:
    """Kısa VAD/konuşma duraklamalarında audio hedefini en az 1.5s korur.

    Kurallar:
    - ACTIVE_SPEAKER ile yeni sektör lock edildiğinde target_yaw sektörde kalır.
    - Tek bir kısa VAD/speech kaybı hedefi hemen düşürmez (en az 1.5s grace period).
    - Bu süre boyunca son aktif sektörün target_yaw'i korunur.
    - Yeni başka sektör doğrulanırsa yeni sektöre geçilir.
    - Vision owner olduğu anda audio tamamen bırakılır.
    - IDLE'ye geçişte grace süresi dolduktan sonra resetlenir.
    """

    def __init__(self, hold_grace_s: float = 1.5):
        self.hold_grace_s = hold_grace_s
        self.retained_target_yaw = None
        self.retained_target_id = None
        self.hold_until = 0.0

    def on_vision_active(self) -> None:
        """Vision devreye girdiği anda audio hedefi derhal bırakılır."""
        self.retained_target_yaw = None
        self.retained_target_id = None
        self.hold_until = 0.0

    def on_active_speaker(self, active_sector, now: float, target_id: Optional[str] = None):
        """ACTIVE_SPEAKER durumunda hedefi günceller ve grace süresini yeniler."""
        if target_id:
            self.retained_target_id = target_id
        if active_sector is not None:
            self.retained_target_yaw = active_sector
            self.hold_until = now + self.hold_grace_s
            return self.retained_target_yaw
        if self.retained_target_yaw is not None and now < self.hold_until:
            return self.retained_target_yaw
        return None

    def on_speech_dropout(self, active_sector, now: float):
        """Konuşma duraklamasında grace period boyunca hedefi tutar."""
        if self.retained_target_yaw is not None and now < self.hold_until:
            # Bu süre içinde yeni bir sektör doğrulanırsa ona geç
            if active_sector is not None and active_sector != self.retained_target_yaw:
                self.retained_target_yaw = active_sector
                self.hold_until = now + self.hold_grace_s
            return self.retained_target_yaw
        # Grace period doldu
        self.retained_target_yaw = None
        self.retained_target_id = None
        self.hold_until = 0.0
        return None

    def reset(self) -> None:
        self.retained_target_yaw = None
        self.retained_target_id = None
        self.hold_until = 0.0


def resolve_target_yaw(
    result,
    detections,
    active_sector: Optional[float],
    target_retention: AudioTargetRetention,
    sector_mapper: AudioSectorMapper,
    now: float,
) -> float:
    """Sektörel Audio -> Head Eşlemesi ve Hedef Koruma (Retention).

    Audio aktif olduğu sürece tek authoritative kaynak AudioSectorMapper +
    AudioTargetRetention'dır. GazeTracker.step() tarafından üretilen continuous
    audio target asla kullanılmaz / dışarı sızmaz.
    """
    if result.owner == PrioritySource.VISUAL_TRACKING or len(detections) > 0:
        # Kural: Vision owner olduğu anda audio tamamen bırakılır
        target_retention.on_vision_active()
        sector_mapper.reset()
        return result.target_yaw_deg

    if result.owner == PrioritySource.ACTIVE_SPEAKER:
        held_yaw = target_retention.on_active_speaker(active_sector, now, getattr(result, "target_id", None))
        if held_yaw is not None:
            result.target_yaw_deg = held_yaw
        else:
            result.target_yaw_deg = 0.0
        return result.target_yaw_deg

    # ACTIVE_SPEAKER veya VISUAL değil (kısa speech dropout / IDLE / ACQUIRING)
    held_yaw = target_retention.on_speech_dropout(active_sector, now)
    if held_yaw is not None:
        result.target_yaw_deg = held_yaw
        result.owner = PrioritySource.ACTIVE_SPEAKER
        result.target_id = target_retention.retained_target_id or result.target_id or "audio_speaker_1"
    else:
        target_retention.reset()
        if result.owner == PrioritySource.IDLE:
            sector_mapper.reset()
        result.target_yaw_deg = 0.0

    return result.target_yaw_deg


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


def main(argv=None) -> int:
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
    parser.add_argument("--audio-hold-grace", type=float, default=1.5,
                        help="Audio hedefinin konuşma kesildikten sonra tutulacağı süre (saniye, varsayılan: 1.5)")
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
    sector_mapper = AudioSectorMapper()
    target_retention = AudioTargetRetention(hold_grace_s=opts.audio_hold_grace)
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

            if voice_loop is not None:
                voice_loop.pump(now)

            # Masadaki sensörler komutla dönmez. Bu modda bilinen sabit
            # referansı ortak beyne veririz; encoder varmış gibi raporlamayız.
            head_reference = (0.0 if opts.fixed_head else
                              head.measured_angle_deg if head.has_feedback else None)

            is_speech = bool(speech.is_speech) if speech is not None else False
            active_sector = sector_mapper.update(doa_deg, is_speech, now)

            result = tracker.step(
                faces=detections,
                frame_size=(frame.shape[1], frame.shape[0]),
                doa_deg=doa_deg,
                speech=speech,
                measured_head_deg=head_reference,
                timestamp=now,
                is_robot_speaking=voice_loop.is_speaking_at(now) if voice_loop else False,
            )

            # Sektörel Audio -> Head Eşlemesi ve Hedef Koruma (Retention):
            resolve_target_yaw(
                result=result,
                detections=detections,
                active_sector=active_sector,
                target_retention=target_retention,
                sector_mapper=sector_mapper,
                now=now,
            )

            head.send_angle(result.target_yaw_deg)
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
                doa_deg=doa_deg,
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
