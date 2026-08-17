#!/usr/bin/env python3
"""ASTRO V1 — Yüz kaydı (enrollment).

Kişileri robotun tanıyabilmesi için yüz vektörlerini veritabanına ekler.
İki yol da desteklenir:

    # 1) Fotoğraflardan (telefondan attığınız kareler de olur)
    ./scripts/enroll_face.py --name Yunus --photos faces/Yunus

    # 2) Kameradan canlı çekim
    ./scripts/enroll_face.py --name Yunus --capture --count 5

    # Yönetim
    ./scripts/enroll_face.py --list
    ./scripts/enroll_face.py --remove Yunus
    ./scripts/enroll_face.py --test bir_foto.jpg      # kim olduğunu söyler

Aynı kişi için farklı açı/ışık koşullarından 3-5 kare eklemek tanımayı belirgin
şekilde sağlamlaştırır. Kayıt ve tanıma aynı motoru (face_db.FaceEngine) kullanır.
"""
import argparse
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "ros2_ws" / "src" / "astro_vision"))

try:
    import cv2
except ImportError:
    sys.exit("❌ opencv-python kurulu değil. Depo venv'ini kullanın: source .venv/bin/activate")

from astro_vision.face_db import FaceEngine, FaceEngineUnavailable  # noqa: E402

PHOTO_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def enroll_from_photos(engine: FaceEngine, name: str, folder: Path, replace: bool) -> int:
    photos = sorted(p for p in folder.iterdir() if p.suffix.lower() in PHOTO_SUFFIXES)
    if not photos:
        print(f"❌ {folder} içinde fotoğraf yok ({', '.join(sorted(PHOTO_SUFFIXES))})")
        return 0

    features = []
    for photo in photos:
        image = cv2.imread(str(photo))
        if image is None:
            print(f"   ⚠  okunamadı: {photo.name}")
            continue
        feature = engine.embed_largest(image)
        if feature is None:
            print(f"   ⚠  yüz bulunamadı: {photo.name}")
            continue
        features.append(feature)
        print(f"   ✓ {photo.name}")

    if features:
        engine.add_person(name, features, replace=replace)
        engine.save()
    return len(features)


def enroll_from_camera(engine: FaceEngine, name: str, camera: int, count: int, replace: bool) -> int:
    cap = cv2.VideoCapture(camera)
    if not cap.isOpened():
        print(f"❌ Kamera açılamadı: /dev/video{camera}")
        return 0

    print(f"📷 Kamera {camera} açık. Yüzünüzü kameraya gösterin; {count} kare alınacak.")
    print("   Her kare arasında açınızı biraz değiştirin (sağa/sola bakın).")

    features = []
    attempts = 0
    try:
        while len(features) < count and attempts < count * 40:
            attempts += 1
            ok, frame = cap.read()
            if not ok:
                continue
            feature = engine.embed_largest(frame)
            if feature is None:
                if attempts % 20 == 0:
                    print("   ... yüz görünmüyor, kameraya bakın")
                continue
            features.append(feature)
            print(f"   ✓ kare {len(features)}/{count}")
            time.sleep(0.8)          # aynı anın kopyasını değil, farklı pozu yakala
    finally:
        cap.release()

    if features:
        engine.add_person(name, features, replace=replace)
        engine.save()
    return len(features)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="ASTRO yüz kaydı", formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--name", help="Kaydedilecek kişinin adı")
    parser.add_argument("--photos", help="Fotoğraf klasörü (varsayılan: faces/<isim>)")
    parser.add_argument("--capture", action="store_true", help="Kameradan canlı çek")
    parser.add_argument("--camera", type=int, default=0, help="Kamera indeksi (varsayılan 0)")
    parser.add_argument("--count", type=int, default=5, help="Canlı çekimde kare sayısı")
    parser.add_argument("--replace", action="store_true", help="Kişinin eski kayıtlarını sil")
    parser.add_argument("--list", action="store_true", help="Kayıtlı kişileri listele")
    parser.add_argument("--remove", help="Kişiyi veritabanından sil")
    parser.add_argument("--test", help="Bir fotoğraftaki kişiyi tanımayı dene")
    parser.add_argument("--db", help="Veritabanı yolu (varsayılan ~/.astro/faces/faces.json)")
    args = parser.parse_args()

    try:
        engine = FaceEngine(db_path=args.db)
    except FaceEngineUnavailable as exc:
        print(f"❌ {exc}")
        return 1

    print(f"📁 Veritabanı: {engine.db_path}")

    if args.list:
        print(f"👥 Kayıtlı: {engine.summary()}")
        return 0

    if args.remove:
        if engine.remove_person(args.remove):
            engine.save()
            print(f"🗑️  Silindi: {args.remove}")
            return 0
        print(f"❌ Kayıtlı değil: {args.remove}")
        return 1

    if args.test:
        image = cv2.imread(args.test)
        if image is None:
            print(f"❌ Okunamadı: {args.test}")
            return 1
        faces = engine.detect(image)
        if len(faces) == 0:
            print("Yüz bulunamadı")
            return 1
        for i, face in enumerate(faces, 1):
            name, score = engine.identify(engine.embed(image, face))
            label = name or "TANINMADI"
            print(f"   Yüz {i}: {label} (benzerlik {score:.3f}, eşik {engine.cosine_threshold})")
        return 0

    if not args.name:
        parser.error("--name gerekli (ya da --list / --remove / --test kullanın)")

    if args.capture:
        added = enroll_from_camera(engine, args.name, args.camera, args.count, args.replace)
    else:
        folder = Path(args.photos) if args.photos else REPO_ROOT / "faces" / args.name
        if not folder.is_dir():
            print(f"❌ Klasör yok: {folder}")
            print(f"   Fotoğrafları oraya koyun ya da --capture ile kameradan çekin.")
            return 1
        added = enroll_from_photos(engine, args.name, folder, args.replace)

    if not added:
        print("❌ Hiç yüz eklenemedi")
        return 1

    print(f"✅ {args.name}: {added} kare eklendi")
    print(f"👥 Kayıtlı: {engine.summary()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
