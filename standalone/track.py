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
import os
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
from astro_base.gaze.head_state import PositionSource  # noqa: E402
from stereo_doa import DEFAULT_MIC_SPACING_M  # noqa: E402
from statuslog import StatusLog  # noqa: E402
from tracker import GazeTracker  # noqa: E402

BOX_COLOUR = (0, 215, 255)
TEXT_COLOUR = (0, 255, 120)


from astro_base.gaze.respeaker_localizer import ReSpeakerAudioLocalizer  # noqa: E402



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


def _camera_arg(val: str):
    if str(val).lower() in ("oak_d", "oakd", "depthai", "auto"):
        return 0
    try:
        return int(val)
    except ValueError:
        raise argparse.ArgumentTypeError(f"Geçersiz kamera indeksi: {val}")


def main(argv=None, hid=None) -> int:
    parser = argparse.ArgumentParser(description="ROS'suz ASTRO yüz/ses takibi")
    parser.add_argument("--camera", type=_camera_arg, default=0, help="Kamera indeksi veya 'oak_d'")
    head_mode = parser.add_mutually_exclusive_group()
    head_mode.add_argument("--serial", "--device", dest="serial", default=None, help="Arduino portu, örn. /dev/astro_arduino veya /dev/ttyACM0")
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
    parser.add_argument("--open-loop", action="store_true",
                        help="Enkoder geri beslemesini devre dışı bırak, kafa açısını "
                             "hareket modelinden açık çevrim tahmin et (titremeyi ve osilasyonu engeller)")
    parser.add_argument("--vision-only", action="store_true",
                        help="Yalnızca görsel (yüz) takibi yap; mikrofon/ses takibini "
                             "tamamen devre dışı bırak (arka plan gürültüsünde savrulmayı önler)")
    opts = parser.parse_args(argv)

    if not opts.no_window and not os.environ.get("DISPLAY"):
        print("ℹ️  DISPLAY bulunamadı (SSH/headless ortam) — pencere açılmayacak (--no-window devrede).")
        opts.no_window = True

    head = HeadLink(port=open_port(opts.serial) if opts.serial else None)
    if opts.fixed_head:
        print("🔌 Sabit kamera/mikrofon teşhisi — kafa referansı 0°, encoder ölçümü yok")
    elif opts.open_loop:
        print("🔌 Açık çevrim modu aktif — motor sürülecek, kafa açısı komuttan tahmin edilecek")
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
    last_visual_target_id: Optional[str] = None
    motor_yaw: float = 0.0
    encoder_stall_start: Optional[float] = None
    encoder_fault_warned: bool = False

    consecutive_camera_fails = 0
    try:
        while True:
            now = time.monotonic()
            if opts.seconds is not None and (now - started) >= opts.seconds:
                break

            ok, frame = camera.read()
            if not ok or frame is None:
                consecutive_camera_fails += 1
                if consecutive_camera_fails > 15:
                    print("⚠️  Kameradan kare gelmiyor")
                    break
                time.sleep(0.05)
                continue
            consecutive_camera_fails = 0

            detections = camera.detect(frame)
            head.poll()

            if audio_was_available and not audio.available:
                # The array check runs on the audio thread and can only fail once the
                # first blocks arrive, after the startup line was already printed.
                print(f"🎤 {audio.error} — yalnızca görüntüyle takip")
                audio_was_available = False

            # ReSpeaker XVF3000 DSP (VOICEACTIVITY + DOAANGLE) localizer update:
            # Audio target üretiminde AudioSource kullanılmaz; tek ve authoritative kaynak ReSpeakerAudioLocalizer'dır.
            if not opts.vision_only:
                localizer.read_and_update(now=now)

            if voice_loop is not None:
                voice_loop.pump(now)

            # Head position authority resolved centrally by HeadStateManager (single owner of virtual yaw)
            hstate = head.state_mgr.evaluate(timestamp=now)
            if opts.fixed_head:
                meas_head = None
                est_head = 0.0
                head_feedback_active = False
            elif opts.open_loop:
                meas_head = None
                est_head = hstate.estimated_yaw_deg if hstate.estimated_yaw_deg is not None else 0.0
                head_feedback_active = False
            elif hstate.position_source == PositionSource.ENCODER and hstate.actual_yaw_deg is not None:
                meas_head = hstate.actual_yaw_deg
                est_head = None
                head_feedback_active = True
            elif hstate.position_source in (PositionSource.VIRTUAL_ENCODER, PositionSource.ESTIMATED) and hstate.estimated_yaw_deg is not None:
                meas_head = None
                est_head = hstate.estimated_yaw_deg
                head_feedback_active = False
            else:
                # UNKNOWN: position is not known; do NOT assume 0.0 as measured
                meas_head = None
                est_head = hstate.estimated_yaw_deg
                head_feedback_active = False

            # GazeTracker.step() çağrısına DOA beslenmez (doa_deg=None).
            # Böylece eski continuous tracker DOA açılarının (-21.2, -36.9, -59.4 vb.)
            # üretilmesi ve dışarı sızması %100 engellenir.
            result = tracker.step(
                faces=detections,
                frame_size=(frame.shape[1], frame.shape[0]),
                doa_deg=None,
                speech=None,
                measured_head_deg=meas_head,
                timestamp=now,
                is_robot_speaking=voice_loop.is_speaking_at(now) if voice_loop else False,
                estimated_head_deg=est_head,
            )

            # Audio target'ın tek ve authoritative kaynağı ReSpeakerAudioLocalizer'dır.
            # Vision önceliği: Görsel takip bir yüze kilitlendiğinde audio bırakılır.
            # Yüz algılamadaki anlık tek/birkaç karelik kesintilerde (hareket bulanıklığı, profil bakış vb.)
            # GazeTracker'ın hedefi koruma (HOLDING_ATTENTION, TARGET_LOST, TRACKING, ORIENTING)
            # ve setpoint açısını tutma mekanizması korunur; kafa hemen 0°'ye fırlatılmaz
            # ve ses dikkati dağıtamaz.
            vision_active = (
                result.owner == PrioritySource.VISUAL_TRACKING
                or result.gaze_state in (
                    GazeStateEnum.TRACKING,
                    GazeStateEnum.HOLDING_ATTENTION,
                    GazeStateEnum.ORIENTING,
                    GazeStateEnum.ACQUIRING,
                    GazeStateEnum.TARGET_LOST,
                )
            )

            current_speech = audio.latest_speech(now) if audio.available else None
            # Ses hedefinin kabul edilmesi için: ya aktif takip devam ediyordur ya da konuşma tespit edilmiştir
            audio_tracking_allowed = (
                not opts.vision_only
                and localizer.is_tracking(now)
            )

            if vision_active:
                localizer.on_vision_active()
                target_yaw = result.target_yaw_deg
                motor_yaw = target_yaw
                last_audio_log_yaw = None
                if result.target_id:
                    last_visual_target_id = result.target_id
                if result.owner != PrioritySource.VISUAL_TRACKING:
                    result.owner = PrioritySource.VISUAL_TRACKING
                    if not result.target_id:
                        result.target_id = last_visual_target_id
            elif audio_tracking_allowed:
                last_visual_target_id = None
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
                last_visual_target_id = None
                last_audio_log_yaw = None
                # FSM kendi grace state'lerini yönetsin (TARGET_LOST → RECOVERING → IDLE).
                # Biz sadece FSM IDLE veya RECOVERING dediğinde 0°'ye dönüyoruz.
                if result.gaze_state in (GazeStateEnum.RECOVERING, GazeStateEnum.IDLE):
                    target_yaw = result.target_yaw_deg  # FSM RECOVERING'de 0.0 döndürür
                    motor_yaw = target_yaw
                    result.owner = PrioritySource.IDLE
                    result.target_id = None
                else:
                    # TARGET_LOST vb: son pozisyonu koru, FSM kararını bekle
                    target_yaw = motor_yaw
                    result.target_yaw_deg = motor_yaw

            clamped_motor_yaw = max(-75.0, min(75.0, float(motor_yaw)))
            head.send_angle(clamped_motor_yaw)
            head.tick(now)

            if vision_active:
                cam_bearing = None
                if detections:
                    cx = float(detections[0].x + (detections[0].w / 2.0))
                    cy = float(detections[0].y + (detections[0].h / 2.0))
                    cam_az, _ = tracker.transformer.camera_pixel_to_optical_angles(
                        cx, cy, frame.shape[1], frame.shape[0]
                    )
                    cam_bearing = round(float(cam_az), 2)
                elif getattr(tracker, "_latest_tracks", None) and len(tracker._latest_tracks) > 0:
                    cam_bearing = round(float(tracker._latest_tracks[0].camera_bearing_deg), 2)

                if hstate.position_source == PositionSource.ENCODER and hstate.actual_yaw_deg is not None:
                    pos_src = "ENCODER"
                    enc_actual = round(float(hstate.actual_yaw_deg), 2)
                else:
                    pos_src = "UNKNOWN"
                    enc_actual = None

                canon_yaw = (
                    round(float(hstate.canonical_yaw_deg), 2)
                    if hstate.canonical_yaw_deg is not None
                    else None
                )

                print(
                    f"[VISUAL_TELEMETRY] "
                    f"target_id={result.target_id} "
                    f"camera_bearing_deg={cam_bearing} "
                    f"canonical_head_yaw_deg={canon_yaw} "
                    f"target_yaw_deg={round(float(target_yaw), 2)} "
                    f"serial_command_deg={round(float(clamped_motor_yaw), 2)} "
                    f"position_source={pos_src} "
                    f"encoder_actual_deg={enc_actual}"
                )

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
                head_feedback=head_feedback_active,
                speech=audio.latest_speech(now) if audio.available else None,
                fixed_head=opts.fixed_head,
            )

            # Bindirme bir kez çizilir: pencere ve kayıt aynı kareyi paylaşır.
            # İki kez çizmek, zaten takılan makinede kare başına maliyeti ikiye katlar.
            if recorder is not None or not opts.no_window:
                overlaid = draw_overlay(frame, detections, result, fps,
                                        audio.available, head_feedback_active, opts.fixed_head)
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
        if tracker.head_feedback_missing and not opts.fixed_head:
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
