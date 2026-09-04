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

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parent))

import core_path  # noqa: F401,E402
from head_link import HeadLink, open_port  # noqa: E402
from sources import AudioSource, CameraSource  # noqa: E402
from tracker import GazeTracker  # noqa: E402

BOX_COLOUR = (0, 215, 255)
TEXT_COLOUR = (0, 255, 120)


def draw_overlay(frame, detections, result, fps: float, audio_ok: bool, head_ok: bool):
    """Boxes, plus the two lines that say which layer is speaking."""
    for det in detections:
        cv2.rectangle(frame, (det.x, det.y), (det.x + det.w, det.y + det.h), BOX_COLOUR, 2)
        cv2.putText(frame, f"{det.confidence:.2f}", (det.x, max(18, det.y - 8)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, BOX_COLOUR, 1, cv2.LINE_AA)

    height, width = frame.shape[:2]
    band = 60
    cv2.rectangle(frame, (0, height - band), (width, height), (0, 0, 0), -1)
    lines = (
        f"{result.gaze_state.value}  owner={result.owner.value}  "
        f"hedef={result.target_id or '-'}  conf={result.confidence:.2f}",
        f"istenen {result.target_yaw_deg:+.1f}  ->  gercek {result.head_angle_deg:+.1f}"
        f"   [{fps:.0f} fps  ses:{'V' if audio_ok else 'X'}  kafa:{'V' if head_ok else 'X'}]",
    )
    for i, text in enumerate(lines):
        cv2.putText(frame, text, (8, height - band + 24 + i * 26),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.52, TEXT_COLOUR, 1, cv2.LINE_AA)
    return frame


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="ROS'suz ASTRO yüz/ses takibi")
    parser.add_argument("--camera", type=int, default=0, help="Kamera indeksi")
    parser.add_argument("--serial", default=None, help="Arduino portu, örn. /dev/ttyACM0")
    parser.add_argument("--audio-device", type=int, default=None, help="Mikrofon indeksi")
    parser.add_argument("--no-window", action="store_true", help="Pencere açma")
    parser.add_argument("--seconds", type=float, default=None, help="Süre sınırı")
    opts = parser.parse_args(argv)

    camera = CameraSource(device=opts.camera)
    if not camera.available:
        print(f"❌ Kamera {opts.camera} açılamadı.")
        return 1
    print(f"📷 Kamera {opts.camera} | yüz algılama: {camera.detector_name}")

    audio = AudioSource(device=opts.audio_device)
    audio.start()
    print("🎤 Mikrofon dizisi hazır" if audio.available
          else f"🎤 Ses yok ({audio.error}) — yalnızca görüntüyle takip")

    head = HeadLink(port=open_port(opts.serial) if opts.serial else None)
    print("🔌 Arduino bağlı" if head.connected
          else "🔌 Arduino yok — açık çevrim, kafa açısı tahmin edilecek")

    tracker = GazeTracker()
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

            result = tracker.step(
                faces=detections,
                frame_size=(frame.shape[1], frame.shape[0]),
                doa_deg=audio.latest_doa_deg(now) if audio.available else None,
                measured_head_deg=head.measured_angle_deg if head.has_feedback else None,
                timestamp=now,
            )

            head.send_angle(result.target_yaw_deg)
            head.tick(now)

            frames += 1
            if now - last_fps_at >= 1.0:
                fps = (frames - last_fps_frames) / (now - last_fps_at)
                last_fps_at, last_fps_frames = now, frames

            if not opts.no_window:
                cv2.imshow("ASTRO — ROS'suz takip",
                           draw_overlay(frame, detections, result, fps,
                                        audio.available, head.has_feedback))
                if cv2.waitKey(1) & 0xFF in (ord("q"), 27):
                    break
    except KeyboardInterrupt:
        pass
    finally:
        elapsed = max(time.monotonic() - started, 1e-6)
        print(f"\n📊 {frames} kare / {elapsed:.1f} sn = {frames / elapsed:.1f} Hz")
        if tracker.head_feedback_missing:
            print("⚠️  Encoder hiç konuşmadı: kafa açısı komuttan tahmin edildi. "
                  "Gerçek açı sapabilir; --serial ile bağlayıp doğrulayın.")
        camera.close()
        audio.close()
        head.close()
        if not opts.no_window:
            cv2.destroyAllWindows()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
