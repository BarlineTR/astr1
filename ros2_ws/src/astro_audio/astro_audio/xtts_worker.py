#!/usr/bin/env python3
"""ASTRO V1 — XTTS sentez işçisi (ayrı süreç, ayrı venv).

Bu dosya ROS'un içinde ÇALIŞMAZ. `tts_node` onu XTTS deposunun kendi
sanal ortamındaki Python ile başlatır (bkz. scripts/install_xtts.sh), çünkü
XTTS numpy 1.26 + torch 2.5 ister, ASTRO ise rclpy ABI'si için numpy 2.2'ye
sabitlenmiştir. Bu yüzden burada `rclpy` veya astro_audio'nun başka bir modülü
import EDİLMEZ; yalnızca XTTS venv'inde bulunan paketler kullanılır.

Süreç kalıcıdır: model ve konuşmacı latent'leri bir kez yüklenir, sonra her
istek yalnızca çıkarım maliyetini öder (aksi hâlde her cümlede 10+ sn model
yükleme).

Protokol — satır tabanlı JSON, stdin/stdout:
    <- {"id": 1, "text": "merhaba", "out": "/tmp/a.wav"}
    -> @@XTTS@@ {"id": 1, "ok": true, "path": "/tmp/a.wav", "rtf": 0.09}

Kütüphane stdout'a bolca log bastığı için yanıtlar @@XTTS@@ önekiyle işaretlenir;
tts_node yalnızca bu satırları ayrıştırır, gerisini debug log'una yazar.
"""
import argparse
import json
import os
import sys
import time

PREFIX = "@@XTTS@@ "


def emit(payload: dict) -> None:
    """Tek satırlık, önekli JSON yanıt gönder."""
    sys.stdout.write(PREFIX + json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def main() -> int:
    parser = argparse.ArgumentParser(description="XTTS persistent synthesis worker")
    parser.add_argument("--speaker-wav", required=True, help="Ses klonlama referans dosyası")
    parser.add_argument("--language", default="tr")
    parser.add_argument("--model", default="tts_models/multilingual/multi-dataset/xtts_v2")
    parser.add_argument("--device", default="auto", choices=["auto", "cuda", "cpu"])
    parser.add_argument("--half", default="1", help="1 = fp16 (yalnızca CUDA'da)")
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--no-warmup", action="store_true")
    args = parser.parse_args()

    # XTTS lisans onayı sorusu etkileşimsiz çalıştırmada süreci kilitler.
    os.environ.setdefault("COQUI_TOS_AGREED", "1")

    try:
        import soundfile as sf
        import torch
        from TTS.api import TTS
    except Exception as exc:  # noqa: BLE001 — sebep tts_node'a aktarılacak
        emit({"event": "error", "stage": "import", "message": f"{type(exc).__name__}: {exc}"})
        return 1

    if not os.path.exists(args.speaker_wav):
        emit({"event": "error", "stage": "speaker", "message": f"referans ses yok: {args.speaker_wav}"})
        return 1

    device = args.device
    if device == "auto":
        device = "cuda" if torch.cuda.is_available() else "cpu"

    try:
        tts = TTS(args.model).to(device)
        model = tts.synthesizer.tts_model
        sample_rate = model.config.audio.output_sample_rate

        # fp16 yalnızca GPU'da anlamlı; CPU'da yarı hassasiyet yavaşlatır.
        half = args.half not in ("0", "false", "False", "") and device == "cuda"
        if half:
            model.use_half_precision()

        # Konuşmacı latent'leri bir kez çıkarılır. tts.tts_to_file() bunları her
        # çağrıda baştan hesaplar; sürekli konuşan bir robotta bu boşa giden zamandır.
        gpt_cond_latent, speaker_embedding = model.get_conditioning_latents(
            audio_path=[args.speaker_wav]
        )

        if not args.no_warmup:
            # İlk çağrı CUDA kernel/bellek kurulumunu da içerir; kullanıcıyı bekletmesin.
            model.inference("Isınma turu.", args.language, gpt_cond_latent, speaker_embedding)
    except Exception as exc:  # noqa: BLE001
        emit({"event": "error", "stage": "load", "message": f"{type(exc).__name__}: {exc}"})
        return 1

    emit(
        {
            "event": "ready",
            "device": device,
            "half": half,
            "sample_rate": sample_rate,
            "gpu": torch.cuda.get_device_name(0) if device == "cuda" else None,
        }
    )

    # ----------------------------------------------------------- istek döngüsü
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError as exc:
            emit({"ok": False, "message": f"geçersiz JSON: {exc}"})
            continue

        if req.get("cmd") == "quit":
            break

        req_id = req.get("id")
        text = (req.get("text") or "").strip()
        out_path = req.get("out")
        if not text or not out_path:
            emit({"id": req_id, "ok": False, "message": "text ve out zorunlu"})
            continue

        try:
            start = time.perf_counter()
            out = model.inference(
                text,
                req.get("language") or args.language,
                gpt_cond_latent,
                speaker_embedding,
                enable_text_splitting=True,
                batch_size=args.batch_size,
            )
            sf.write(out_path, out["wav"], sample_rate)
            elapsed = time.perf_counter() - start
            audio_seconds = len(out["wav"]) / sample_rate
            emit(
                {
                    "id": req_id,
                    "ok": True,
                    "path": out_path,
                    "seconds": round(audio_seconds, 2),
                    "rtf": round(elapsed / audio_seconds, 3) if audio_seconds else None,
                }
            )
        except Exception as exc:  # noqa: BLE001 — işçi ölmesin, hata rapor edilsin
            emit({"id": req_id, "ok": False, "message": f"{type(exc).__name__}: {exc}"})

    return 0


if __name__ == "__main__":
    sys.exit(main())
