#!/usr/bin/env python3
"""ASTRO V1 — Ses kaydı (konuşmacı tanıma için).

Kişilerin sesini tanıtır; robot konuşanın kim olduğunu ayırt edebilsin diye.
Yüz kaydının (enroll_face.py) ses karşılığıdır ve aynı isimleri kullanmalıdır.

    # 1) Ses dosyalarından (wav)
    ./scripts/enroll_speaker.py --name Yunus --audio voices/Yunus

    # 2) Mikrofondan canlı kayıt
    ./scripts/enroll_speaker.py --name Yunus --record --count 3 --seconds 5

    # Yönetim
    ./scripts/enroll_speaker.py --list
    ./scripts/enroll_speaker.py --remove Yunus
    ./scripts/enroll_speaker.py --test kayit.wav

Her kişi için 3-5 ayrı kayıt (farklı cümleler, normal konuşma temposu) tanımayı
belirgin biçimde sağlamlaştırır. Kayıt başına en az ~3 saniye konuşma önerilir.
"""
import argparse
import sys
import wave
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "ros2_ws" / "src" / "astro_audio"))

from astro_audio.speaker_db import (  # noqa: E402
    SAMPLE_RATE,
    SpeakerEngine,
    SpeakerEngineUnavailable,
    to_16k_mono,
)

AUDIO_SUFFIXES = {".wav", ".wave"}


def load_audio(path: Path) -> np.ndarray | None:
    try:
        with wave.open(str(path)) as w:
            if w.getsampwidth() != 2:
                print(f"   ⚠  yalnızca 16-bit WAV destekleniyor: {path.name}")
                return None
            raw = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
            return to_16k_mono(raw, w.getframerate(), w.getnchannels())
    except (wave.Error, OSError) as exc:
        print(f"   ⚠  okunamadı ({exc}): {path.name}")
        return None


def enroll_from_files(engine: SpeakerEngine, name: str, folder: Path, replace: bool) -> int:
    files = sorted(p for p in folder.iterdir() if p.suffix.lower() in AUDIO_SUFFIXES)
    if not files:
        print(f"❌ {folder} içinde WAV yok")
        return 0

    embeddings = []
    for path in files:
        audio = load_audio(path)
        if audio is None:
            continue
        embedding = engine.embed(audio)
        if embedding is None:
            print(f"   ⚠  çok kısa (en az {engine.__class__.__module__ and '0.6'} sn): {path.name}")
            continue
        embeddings.append(embedding)
        print(f"   ✓ {path.name} ({audio.size / SAMPLE_RATE:.1f} sn)")

    if embeddings:
        engine.add_person(name, embeddings, replace=replace)
        engine.save()
    return len(embeddings)


def enroll_from_mic(engine: SpeakerEngine, name: str, count: int, seconds: float,
                    device, replace: bool) -> int:
    try:
        import sounddevice as sd
    except ImportError:
        print("❌ sounddevice kurulu değil — dosyadan kayıt kullanın (--audio)")
        return 0

    if device is None:
        try:
            for idx, dev in enumerate(sd.query_devices()):
                if dev.get("max_input_channels", 0) > 0:
                    d_name = dev.get("name", "").lower()
                    if any(h in d_name for h in ["respeaker", "uac1", "seeed", "arrayuac", "usb audio"]):
                        device = idx
                        print(f"   🎤 ReSpeaker mikrofon seçildi: [{idx}] {dev.get('name')}")
                        break
        except Exception:
            pass

    embeddings = []
    print(f"🎙️  {count} kayıt alınacak, her biri {seconds:g} saniye.")
    for i in range(1, count + 1):
        input(f"   [{i}/{count}] Hazırsanız Enter'a basıp konuşmaya başlayın...")
        try:
            audio = sd.rec(int(seconds * SAMPLE_RATE), samplerate=SAMPLE_RATE,
                           channels=1, dtype="int16", device=device)
            sd.wait()
        except Exception as exc:
            print(f"   ❌ kayıt alınamadı: {exc}")
            return len(embeddings)

        audio = audio.flatten()
        level = int(np.sqrt(np.mean(audio.astype(np.float32) ** 2)))
        if level < 40:
            print(f"   ⚠  ses çok kısık (RMS {level}) — mikrofona yaklaşıp tekrar deneyin")
            continue
        embedding = engine.embed(audio)
        if embedding is None:
            print("   ⚠  kayıt çok kısa")
            continue
        embeddings.append(embedding)
        print(f"   ✓ kayıt {len(embeddings)} alındı (RMS {level})")


    if embeddings:
        engine.add_person(name, embeddings, replace=replace)
        engine.save()
    return len(embeddings)


def main() -> int:
    parser = argparse.ArgumentParser(description="ASTRO konuşmacı kaydı")
    parser.add_argument("--name", help="Kaydedilecek kişinin adı")
    parser.add_argument("--audio", help="WAV klasörü (varsayılan: voices/<isim>)")
    parser.add_argument("--record", action="store_true", help="Mikrofondan canlı kaydet")
    parser.add_argument("--count", type=int, default=3, help="Canlı kayıt adedi")
    parser.add_argument("--seconds", type=float, default=5.0, help="Her kaydın süresi")
    parser.add_argument("--device", help="Mikrofon indeksi/adı (varsayılan: sistem girişi)")
    parser.add_argument("--replace", action="store_true", help="Eski kayıtları sil")
    parser.add_argument("--list", action="store_true", help="Kayıtlı kişileri listele")
    parser.add_argument("--remove", help="Kişiyi sil")
    parser.add_argument("--test", help="Bir WAV'daki kişiyi tanımayı dene")
    parser.add_argument("--db", help="Veritabanı yolu")
    args = parser.parse_args()

    try:
        engine = SpeakerEngine(db_path=args.db)
    except SpeakerEngineUnavailable as exc:
        print(f"❌ {exc}")
        return 1

    print(f"📁 Veritabanı: {engine.db_path}  (eşik {engine.threshold})")

    if args.list:
        print(f"🗣️  Kayıtlı: {engine.summary()}")
        return 0

    if args.remove:
        if engine.remove_person(args.remove):
            engine.save()
            print(f"🗑️  Silindi: {args.remove}")
            return 0
        print(f"❌ Kayıtlı değil: {args.remove}")
        return 1

    if args.test:
        audio = load_audio(Path(args.test))
        if audio is None:
            return 1
        embedding = engine.embed(audio)
        if embedding is None:
            print("❌ Kayıt çok kısa")
            return 1
        name, score = engine.identify(embedding)
        print(f"   Konuşan: {name or 'TANINMADI'} (benzerlik {score:.3f})")
        return 0

    if not args.name:
        parser.error("--name gerekli (ya da --list / --remove / --test)")

    if args.record:
        device = args.device
        if device is not None and device.isdigit():
            device = int(device)
        added = enroll_from_mic(engine, args.name, args.count, args.seconds, device, args.replace)
    else:
        folder = Path(args.audio) if args.audio else REPO_ROOT / "voices" / args.name
        if not folder.is_dir():
            print(f"❌ Klasör yok: {folder}")
            print("   WAV dosyalarını oraya koyun ya da --record ile mikrofondan kaydedin.")
            return 1
        added = enroll_from_files(engine, args.name, folder, args.replace)

    if not added:
        print("❌ Hiç kayıt eklenemedi")
        return 1

    print(f"✅ {args.name}: {added} kayıt eklendi")
    print(f"🗣️  Kayıtlı: {engine.summary()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
