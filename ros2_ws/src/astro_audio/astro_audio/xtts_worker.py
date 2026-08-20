#!/usr/bin/env python3
"""ASTRO V1 — High-Performance XTTS v2 Persistent Worker on CUDA GPU.

This worker runs inside the dedicated XTTS venv (Python 3.10 + Torch with CUDA 12.6).
It stays resident in GPU memory, maintains a persistent model and conditioning latent cache,
and processes JSON IPC synthesis requests with sub-second latency in FP16 inference mode.

Features:
  - Strict CUDA enforcement (explicit error on CPU fallback attempt)
  - Persistent FP16 model in VRAM (device: cuda:0)
  - Cached speaker conditioning latents (computed once per voice reference)
  - torch.inference_mode() execution with zero gradient overhead
  - Startup pre-warm inference
  - Sub-millisecond latency & GPU VRAM telemetry reporting
  - Generation ID tracking & Barge-in cancellation support
"""

import argparse
import base64
import json
import os
import sys
import time

PREFIX = "@@XTTS@@ "
_LATENT_CACHE = {}


def emit(payload: dict) -> None:
    """Sends a single-line prefixed JSON response to stdout."""
    sys.stdout.write(PREFIX + json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def get_gpu_memory_mb() -> float:
    try:
        import torch
        if torch.cuda.is_available():
            return round(torch.cuda.memory_allocated(0) / (1024 * 1024), 1)
    except Exception:
        pass
    return 0.0


def main() -> int:
    parser = argparse.ArgumentParser(description="ASTRO V1 High-Performance XTTS GPU Worker")
    parser.add_argument("--speaker-wav", required=True, help="Speaker reference WAV file for cloning")
    parser.add_argument("--language", default="tr")
    parser.add_argument("--model", default="tts_models/multilingual/multi-dataset/xtts_v2")
    parser.add_argument("--checkpoint", help="Custom model checkpoint path")
    parser.add_argument("--config", dest="config_path", help="Custom model config path")
    parser.add_argument("--vocab", help="Custom model vocab path")
    parser.add_argument("--speakers", help="Custom model speakers path")
    parser.add_argument("--device", default="cuda", choices=["auto", "cuda", "cpu"])
    parser.add_argument("--half", default="1", help="1 = fp16 (recommended for CUDA)")
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--temperature", type=float, default=float(os.getenv("TTS_XTTS_TEMPERATURE", "0.50")))
    parser.add_argument("--length-penalty", type=float, default=float(os.getenv("TTS_XTTS_LENGTH_PENALTY", "1.0")))
    parser.add_argument("--repetition-penalty", type=float, default=float(os.getenv("TTS_XTTS_REPETITION_PENALTY", "4.0")))
    parser.add_argument("--top-k", type=int, default=int(os.getenv("TTS_XTTS_TOP_K", "45")))
    parser.add_argument("--top-p", type=float, default=float(os.getenv("TTS_XTTS_TOP_P", "0.65")))
    parser.add_argument("--speed", type=float, default=float(os.getenv("TTS_XTTS_SPEED", "1.05")))
    parser.add_argument("--no-warmup", action="store_true")
    args = parser.parse_args()

    os.environ.setdefault("COQUI_TOS_AGREED", "1")
    os.environ["PYTHONNOUSERSITE"] = "1"

    def compute_file_sha256(filepath: Optional[str]) -> str:
        if not filepath or not os.path.exists(filepath):
            return "none"
        try:
            import hashlib
            hasher = hashlib.sha256()
            with open(filepath, "rb") as f:
                for chunk in iter(lambda: f.read(65536), b""):
                    hasher.update(chunk)
            return hasher.hexdigest()
        except Exception as e:
            return f"error:{e}"

    import traceback

    # 1. Dependency Imports & PyTorch 2.6+ Compatibility Monkeypatch
    try:
        import soundfile as sf
        import torch
        import numpy as np

        try:
            _orig_torch_load = torch.load
            def _astro_safe_torch_load(*args, **kwargs):
                if "weights_only" not in kwargs:
                    kwargs["weights_only"] = False
                return _orig_torch_load(*args, **kwargs)
            torch.load = _astro_safe_torch_load
        except Exception:
            pass

        from TTS.api import TTS
    except Exception as exc:
        tb = traceback.format_exc()
        sys.stderr.write(f"[XTTS Worker Import Exception]:\n{tb}\n")
        sys.stderr.flush()
        emit({"event": "error", "stage": "import", "message": f"Import failed: {type(exc).__name__}: {exc}", "traceback": tb})
        return 1

    # 2. Strict CUDA Validation
    device = args.device
    if device == "auto":
        device = "cuda" if torch.cuda.is_available() else "cpu"

    if device == "cuda" and not torch.cuda.is_available():
        msg = "CUDA is requested but torch.cuda.is_available() is False. Refusing silent CPU fallback!"
        sys.stderr.write(f"[XTTS Worker Device Error]: {msg}\n")
        sys.stderr.flush()
        emit({"event": "error", "stage": "device", "message": msg})
        return 1

    if not os.path.exists(args.speaker_wav):
        msg = f"Speaker reference audio not found: {args.speaker_wav}"
        sys.stderr.write(f"[XTTS Worker Speaker Error]: {msg}\n")
        sys.stderr.flush()
        emit({"event": "error", "stage": "speaker", "message": msg})
        return 1

    # 3. Model Loading & GPU Residency
    t_load_start = time.perf_counter()
    checkpoint_sha = "none"
    try:
        if args.checkpoint:
            from TTS.tts.configs.xtts_config import XttsConfig
            from TTS.tts.models.xtts import Xtts

            ckpt_dir = os.path.dirname(os.path.abspath(args.checkpoint))

            # Auto-resolve config path if omitted
            cfg_path = args.config_path
            if not cfg_path or not os.path.exists(cfg_path):
                cand_cfg = os.path.join(ckpt_dir, "config.json")
                if os.path.exists(cand_cfg):
                    cfg_path = cand_cfg

            if not cfg_path or not os.path.exists(cfg_path):
                raise FileNotFoundError(f"XTTS config.json not found for checkpoint: {args.checkpoint}")

            # Auto-resolve vocab path if omitted
            vocab_path = args.vocab
            if not vocab_path or not os.path.exists(vocab_path):
                cand_vocab = os.path.join(ckpt_dir, "vocab.json")
                if os.path.exists(cand_vocab):
                    vocab_path = cand_vocab

            # Auto-resolve speakers path if omitted
            speakers_path = args.speakers
            if not speakers_path or not os.path.exists(speakers_path):
                cand_spk = os.path.join(ckpt_dir, "speakers_xtts.pth")
                if os.path.exists(cand_spk):
                    speakers_path = cand_spk

            config = XttsConfig()
            config.load_json(cfg_path)
            model = Xtts.init_from_config(config)
            model.load_checkpoint(
                config,
                checkpoint_path=args.checkpoint,
                vocab_path=vocab_path,
                speaker_file_path=speakers_path,
                eval=True,
                use_deepspeed=False,
            )
            model.to(device)
            model_label = args.checkpoint
            checkpoint_sha = compute_file_sha256(args.checkpoint)
            args.config_path = cfg_path
            args.vocab = vocab_path
            args.speakers = speakers_path
        else:
            tts = TTS(args.model).to(device)
            model = tts.synthesizer.tts_model
            model_label = args.model

        sample_rate = model.config.audio.output_sample_rate

        # FP16 Half Precision
        half = args.half not in ("0", "false", "False", "") and device == "cuda"
        if half:
            model.use_half_precision()

        model.eval()

        # 4. Extract and Cache Speaker Conditioning Latents
        def get_or_extract_latents(spk_path: str):
            abs_path = os.path.abspath(spk_path)
            if abs_path not in _LATENT_CACHE:
                with torch.inference_mode():
                    g_latent, spk_emb = model.get_conditioning_latents(audio_path=[abs_path])
                    _LATENT_CACHE[abs_path] = (g_latent, spk_emb)
            return _LATENT_CACHE[abs_path]

        gpt_cond_latent, speaker_embedding = get_or_extract_latents(args.speaker_wav)

        # 5. Startup Warm-up Inference (CUDA Kernel compilation & VRAM pre-allocation)
        t_warmup_ms = 0.0
        if not args.no_warmup:
            t_w_start = time.perf_counter()
            with torch.inference_mode():
                model.inference(
                    "Robot hazır.",
                    args.language,
                    gpt_cond_latent,
                    speaker_embedding,
                    temperature=args.temperature,
                    length_penalty=args.length_penalty,
                    repetition_penalty=args.repetition_penalty,
                    top_k=args.top_k,
                    top_p=args.top_p,
                    speed=args.speed,
                    enable_text_splitting=False,
                )
            t_warmup_ms = (time.perf_counter() - t_w_start) * 1000.0

    except Exception as exc:
        tb = traceback.format_exc()
        sys.stderr.write(f"[XTTS Worker Load Exception]:\n{tb}\n")
        sys.stderr.flush()
        emit({"event": "error", "stage": "load", "message": f"Model load failed: {type(exc).__name__}: {exc}", "traceback": tb})
        return 1

    t_load_ms = (time.perf_counter() - t_load_start) * 1000.0
    gpu_mem_mb = get_gpu_memory_mb()
    gpu_name = torch.cuda.get_device_name(0) if device == "cuda" else "CPU"

    emit({
        "event": "ready",
        "device": device,
        "half": half,
        "sample_rate": sample_rate,
        "model": model_label,
        "xtts_model_path": os.path.abspath(args.checkpoint) if args.checkpoint else args.model,
        "xtts_config_path": os.path.abspath(args.config_path) if args.config_path else "default",
        "xtts_vocab_path": os.path.abspath(args.vocab) if args.vocab else "default",
        "xtts_speakers_path": os.path.abspath(args.speakers) if args.speakers else "default",
        "xtts_reference_wav": os.path.abspath(args.speaker_wav),
        "xtts_checkpoint_sha256": checkpoint_sha,
        "temperature": args.temperature,
        "length_penalty": args.length_penalty,
        "repetition_penalty": args.repetition_penalty,
        "top_k": args.top_k,
        "top_p": args.top_p,
        "speed": args.speed,
        "gpu": gpu_name,
        "gpu_memory_mb": gpu_mem_mb,
        "load_time_ms": round(t_load_ms, 1),
        "warmup_time_ms": round(t_warmup_ms, 1),
        "cached_speakers": list(_LATENT_CACHE.keys()),
    })

    # 6. Persistent Request Processing Loop
    current_active_gen_id = 0

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError as exc:
            emit({"ok": False, "message": f"Invalid JSON IPC: {exc}"})
            continue

        cmd = req.get("cmd")
        if cmd == "quit":
            break
        elif cmd == "interrupt" or cmd == "cancel":
            target_gen = req.get("gen_id", 0)
            current_active_gen_id = max(current_active_gen_id, target_gen)
            emit({"event": "interrupted", "gen_id": target_gen, "ok": True})
            continue
        elif cmd == "cache_speaker":
            spk_wav = req.get("speaker_wav")
            if spk_wav and os.path.exists(spk_wav):
                try:
                    get_or_extract_latents(spk_wav)
                    emit({"ok": True, "event": "speaker_cached", "path": spk_wav})
                except Exception as ce:
                    emit({"ok": False, "event": "speaker_cache_failed", "message": str(ce)})
            continue

        req_id = req.get("id")
        gen_id = req.get("gen_id", 0)
        text = (req.get("text") or "").strip()
        out_path = req.get("out")
        return_pcm = bool(req.get("return_pcm", False))

        if gen_id < current_active_gen_id:
            emit({"id": req_id, "gen_id": gen_id, "ok": False, "cancelled": True, "message": "Turn superseded by newer generation"})
            continue

        if not text:
            emit({"id": req_id, "gen_id": gen_id, "ok": False, "message": "Empty text provided"})
            continue

        req_spk_wav = req.get("speaker_wav") or args.speaker_wav
        try:
            req_cond_latent, req_spk_emb = get_or_extract_latents(req_spk_wav)
        except Exception as exc:
            req_cond_latent, req_spk_emb = gpt_cond_latent, speaker_embedding

        try:
            t_infer_start = time.perf_counter()
            with torch.inference_mode():
                out = model.inference(
                    text,
                    req.get("language") or args.language,
                    req_cond_latent,
                    req_spk_emb,
                    temperature=float(req.get("temperature", args.temperature)),
                    length_penalty=float(req.get("length_penalty", args.length_penalty)),
                    repetition_penalty=float(req.get("repetition_penalty", args.repetition_penalty)),
                    top_k=int(req.get("top_k", args.top_k)),
                    top_p=float(req.get("top_p", args.top_p)),
                    speed=float(req.get("speed", args.speed)),
                    enable_text_splitting=False,  # Sentence chunker already handles splitting
                )
            t_infer_end = time.perf_counter()
            gpu_infer_ms = (t_infer_end - t_infer_start) * 1000.0

            wav_data = out["wav"]
            audio_seconds = len(wav_data) / sample_rate
            rtf = round((gpu_infer_ms / 1000.0) / audio_seconds, 3) if audio_seconds > 0 else 0.0

            # Write file if out_path specified
            if out_path:
                sf.write(out_path, wav_data, sample_rate)

            pcm_b64 = None
            if return_pcm:
                # Convert float32 [-1.0, 1.0] to int16 PCM bytes
                int16_arr = (np.clip(wav_data, -1.0, 1.0) * 32767.0).astype(np.int16)
                pcm_b64 = base64.b64encode(int16_arr.tobytes()).decode("ascii")

            emit({
                "id": req_id,
                "gen_id": gen_id,
                "ok": True,
                "path": out_path or "",
                "pcm_base64": pcm_b64,
                "sample_rate": sample_rate,
                "seconds": round(audio_seconds, 3),
                "gpu_inference_ms": round(gpu_infer_ms, 1),
                "rtf": rtf,
                "gpu_memory_mb": get_gpu_memory_mb(),
            })

        except Exception as exc:
            emit({"id": req_id, "gen_id": gen_id, "ok": False, "message": f"Synthesis error: {type(exc).__name__}: {exc}"})

    return 0


if __name__ == "__main__":
    sys.exit(main())
