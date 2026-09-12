#!/usr/bin/env python3
"""ASTRO V1 — Standalone Local Gemma 4 E2B Q4_K_S + Edge-TTS Performance & Latency Benchmark.

Allows developers and operators to test the complete zero-cloud fallback pipeline
without launching the full ROS2 robotics stack (no motors, camera, or lidar required).

Features:
  - Validates llama.cpp llama-server health (GET /health)
  - Benchmarks TTFT (Time To First Token) via SSE streaming
  - Benchmarks TTFC (Time To First Clause) via SentenceChunker
  - Benchmarks TTFA (Time To First Audio) via Edge-TTS synthesis
  - Measures total generation latency, tokens/second, and audio RTF
  - Supports `--simulate` mode when llama-server is not actively running
"""

import argparse
import io
import os
import sys
import time
from typing import Generator, List, Optional

# Set up package paths
_current_dir = os.path.dirname(os.path.abspath(__file__))
_repo_root = os.path.abspath(os.path.join(_current_dir, ".."))
_ws_src = os.path.join(_repo_root, "ros2_ws", "src")
for _pkg in ["astro_ai", "astro_audio", "astro_vision", "astro_base"]:
    _p = os.path.join(_ws_src, _pkg)
    if _p not in sys.path:
        sys.path.insert(0, _p)

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

try:
    from astro_ai.local_gemma_client import LocalGemmaClient, LocalGemmaError
except ImportError:
    LocalGemmaClient = None  # type: ignore

try:
    from astro_audio.sentence_chunker import SentenceChunker, clean_text_for_tts
except ImportError:
    SentenceChunker = None  # type: ignore

try:
    from astro_audio.edge_tts_engine import EdgeTTSEngine
except ImportError:
    EdgeTTSEngine = None  # type: ignore


def simulate_gemma_tokens(user_query: str) -> Generator[str, None, None]:
    """Simulates token-by-token SSE streaming for offline pipeline validation."""
    tokens = [
        "Selam", "! ", "Ben ", "Astro", ", ",
        "seninle ", "tanıştığıma ", "çok ", "memnun ", "oldum", ". ",
        "Bugün ", "harika ", "bir ", "gün", "!"
    ]
    for tok in tokens:
        time.sleep(0.045)  # simulate ~22 tok/s on Jetson Orin / Local GPU
        yield tok


def find_llama_server_binary() -> Optional[str]:
    """Finds llama-server executable in common build directories or PATH."""
    import shutil
    w = shutil.which("llama-server")
    if w:
        return w
    home = os.path.expanduser("~")
    candidates = [
        os.path.join(home, "Desktop", "llama.cpp", "build", "bin", "llama-server"),
        os.path.join(home, "Desktop", "llama.cpp", "llama-server"),
        os.path.join(home, "Desktop", "llama.cpp", "build", "bin", "server"),
        os.path.join(home, "Desktop", "llama.cpp", "server"),
        os.path.join(home, "llama.cpp", "build", "bin", "llama-server"),
        os.path.join(home, "llama.cpp", "llama-server"),
        "/usr/local/bin/llama-server",
    ]
    for c in candidates:
        if os.path.isfile(c):
            return c
    return None


def run_benchmark(
    user_query: str,
    base_url: str = "http://127.0.0.1:8080",
    n_predict: int = 12,
    temperature: float = 0.2,
    simulate: bool = False,
    play_audio: bool = False,
):
    print("\n" + "=" * 76)
    print(" 🚀 ASTRO LOCAL FALLBACK PIPELINE — LATENCY & PERFORMANCE BENCHMARK")
    print("=" * 76)
    print(f"  Girdi Sorgusu      : \"{user_query}\"")
    print(f"  llama.cpp Uç Nokta : {base_url}/completion")
    print(f"  Parametreler       : n_predict={n_predict}, temperature={temperature}")
    print("=" * 76 + "\n")

    client = LocalGemmaClient(base_url=base_url) if LocalGemmaClient else None
    is_live = False

    if not simulate and client:
        print("🔍 [1/4] llama-server Sağlık Kontrolü (GET /health)...", end=" ", flush=True)
        is_live = client.health_check(timeout_s=1.0)
        if is_live:
            print("✅ ÇEVRİMİÇİ (status: ok)")
        else:
            print("❌ ÇEVRİMDIŞI")
            server_bin = find_llama_server_binary()
            bin_cmd = server_bin if server_bin else "llama-server"
            print("\n" + "-" * 76)
            print("  ⚠️  llama-server 127.0.0.1:8080 üzerinde bulunamadı!")
            print(f"  Gemma 4 E2B Q4_K_S modelini başlatmak için çalıştırın:")
            print(f"    {bin_cmd} -m gemma-4-E2B-it-Q4_K_S.gguf --port 8080 -c 2048 -ngl 99 --host 127.0.0.1")
            print("  Boru hattı testine simülasyon moduyla (--simulate) devam ediliyor...")
            print("-" * 76 + "\n")
            simulate = True
    else:
        print("ℹ️ [1/4] llama-server simülasyon modu devrede.")

    gemma_prompt = (
        "ASTRO bir sosyal robot. Türkçe konuş. Kısa ve doğal cevap ver.\n\n"
        f"Kullanıcı: {user_query}\n"
        "ASTRO:"
    )

    chunker = SentenceChunker(min_first_clause_chars=6, min_clause_chars=20) if SentenceChunker else None
    edge_engine = EdgeTTSEngine(voice="tr-TR-AhmetNeural", timeout_s=4.0) if EdgeTTSEngine else None

    # Performance tracking metrics
    t_start = time.perf_counter()
    t_first_token: Optional[float] = None
    t_first_clause: Optional[float] = None
    t_first_audio: Optional[float] = None

    tokens_received: List[str] = []
    ready_clauses: List[str] = []
    first_clause_text: Optional[str] = None
    first_clause_pcm: Optional[bytes] = None
    tts_infer_ms = 0.0
    synth_thread: Optional[threading.Thread] = None

    def _synth_worker(text_to_synth: str):
        nonlocal first_clause_pcm, t_first_audio, tts_infer_ms
        if edge_engine and edge_engine.is_installed:
            t0_s = time.perf_counter()
            try:
                pcm = edge_engine.synthesize_sentence(text_to_synth, generation_id=1)
                t1_s = time.perf_counter()
                tts_infer_ms = (t1_s - t0_s) * 1000.0
                first_clause_pcm = pcm
                t_first_audio = t1_s
            except Exception as _e:
                tts_infer_ms = 0.0

    print("⚡ [2/4] Token Akışı Başlatılıyor...", flush=True)

    token_stream: Generator[str, None, None]
    if simulate or not is_live:
        token_stream = simulate_gemma_tokens(user_query)
    else:
        token_stream = client.stream(
            prompt=gemma_prompt,
            n_predict=n_predict,
            temperature=temperature,
            timeout=3.0,
        )

    try:
        for token in token_stream:
            now = time.perf_counter()
            if t_first_token is None:
                t_first_token = now

            tokens_received.append(token)
            print(token, end="", flush=True)

            if chunker:
                new_clauses = chunker.feed(token)
                for cl in new_clauses:
                    ready_clauses.append(cl)
                    if t_first_clause is None:
                        t_first_clause = time.perf_counter()
                        first_clause_text = cl
                        import threading
                        synth_thread = threading.Thread(target=_synth_worker, args=(cl,), daemon=True)
                        synth_thread.start()

        # Flush any trailing clause
        if chunker:
            rem = chunker.flush()
            if rem:
                ready_clauses.append(rem)
                if t_first_clause is None:
                    t_first_clause = time.perf_counter()
                    first_clause_text = rem

    except Exception as exc:
        print(f"\n❌ [HATA] LLM Akış Hatası: {exc}")
        return

    t_llm_end = time.perf_counter()
    print("\n")

    full_response = "".join(tokens_received).strip()
    clause_to_synth = first_clause_text or full_response

    # Wait for concurrent first-clause synthesis if already in flight
    if synth_thread:
        synth_thread.join(timeout=4.0)

    # Fallback to synchronous synthesis if not already synthesized
    if not first_clause_pcm:
        print(f"🎵 [3/4] İlk Cümlecik Edge-TTS'e Gönderiliyor: \"{clause_to_synth}\"...", flush=True)
        if edge_engine and edge_engine.is_installed:
            t_tts_start = time.perf_counter()
            try:
                pcm = edge_engine.synthesize_sentence(clause_to_synth, generation_id=1)
                t_tts_end = time.perf_counter()
                tts_infer_ms = (t_tts_end - t_tts_start) * 1000.0
                if pcm:
                    first_clause_pcm = pcm
                    t_first_audio = t_tts_end
                    print(f"  ✅ TTS Sentezi Tamamlandı: {len(pcm)} bayt ({tts_infer_ms:.1f}ms)")
                else:
                    print("  ⚠️ TTS boş ses üretti.")
            except Exception as tts_err:
                print(f"  ⚠️ Edge-TTS hatası: {tts_err}")
        else:
            print("  ℹ️ Edge-TTS kütüphanesi ortamda yüklü değil (mock TTS süresi hesaplanıyor: ~120ms)")
            tts_infer_ms = 120.0
            t_first_audio = (t_first_clause or t_llm_end) + 0.120
    else:
        print(f"🎵 [3/4] İlk Cümlecik Paralel Sentezlendi: \"{first_clause_text}\" ({tts_infer_ms:.1f}ms)", flush=True)

    # 4. Telemetry and Latency Calculations
    ttft_ms = ((t_first_token - t_start) * 1000.0) if t_first_token else 0.0
    ttfc_ms = ((t_first_clause - t_start) * 1000.0) if t_first_clause else ((t_llm_end - t_start) * 1000.0)
    ttfa_ms = ((t_first_audio - t_start) * 1000.0) if t_first_audio else (ttfc_ms + tts_infer_ms)
    total_gen_ms = (t_llm_end - t_start) * 1000.0
    tok_count = len(tokens_received)
    tok_per_sec = (tok_count / (total_gen_ms / 1000.0)) if total_gen_ms > 0 else 0.0

    audio_dur_s = (len(first_clause_pcm) / 2 / 24000.0) if first_clause_pcm else 0.0

    print("\n" + "=" * 76)
    print(" 📊 DETAYLI GECİKME VE PERFORMANS RAPORU")
    print("=" * 76)
    print(f"  Üretilen Toplam Metin  : \"{full_response}\"")
    print(f"  Token Sayısı           : {tok_count} token")
    print(f"  Token Üretim Hızı      : {tok_per_sec:.1f} tok/s")
    print("-" * 76)
    print(f"  1. TTFT (İlk Token)    : {ttft_ms:6.1f} ms  (Kullanıcı konuşması bittikten ilk kelimeye)")
    print(f"  2. TTFC (İlk Cümlecik) : {ttfc_ms:6.1f} ms  (İlk anlamlı cümle TTS'e aktarılana kadar)")
    print(f"  3. TTS Infer Süresi    : {tts_infer_ms:6.1f} ms  (Edge-TTS AhmetNeural sentez süresi)")
    print(f"  4. TTFA (İLK SES ANI)  : {ttfa_ms:6.1f} ms  🎯 (KULLANICININ HOPARLÖRDEN SESİ DUYMA ANI)")
    print(f"  5. Toplam LLM Süresi   : {total_gen_ms:6.1f} ms")
    if audio_dur_s > 0:
        print(f"  6. Ses Süresi          : {audio_dur_s:6.2f} s   ({len(first_clause_pcm)} bayt, 24kHz int16)")
    print("=" * 76)

    # Optional local speaker playback
    if play_audio and first_clause_pcm:
        print("\n🔊 [Hoparlör Çalma]: Sentezlenen ses çalınıyor...", flush=True)
        try:
            import subprocess
            subprocess.run(
                ["aplay", "-r", "24000", "-f", "S16_LE", "-c", "1", "-q"],
                input=first_clause_pcm,
                check=False,
            )
        except Exception as p_err:
            print(f"  ⚠️ Hoparlör çalma uyarısı: {p_err}")

    # Acceptance threshold evaluation
    target_ttfa_ms = 850.0
    if ttfa_ms <= target_ttfa_ms:
        print(f"  🎉 SONUÇ: MÜKEMMEL! TTFA {ttfa_ms:.1f}ms <= {target_ttfa_ms}ms hedefini karşılıyor.")
    else:
        print(f"  ⚠️ SONUÇ: TTFA {ttfa_ms:.1f}ms > {target_ttfa_ms}ms (Ağ veya model yüküne bağlı gecikme).")
    print("=" * 76 + "\n")


def main():
    parser = argparse.ArgumentParser(description="ASTRO Local Gemma + Edge-TTS Pipeline Benchmark")
    parser.add_argument("--query", "-q", default="Merhaba Astro, bugün nasılsın?", help="Test edilecek kullanıcı sorusu")
    parser.add_argument("--url", default="http://127.0.0.1:8080", help="llama.cpp server base URL")
    parser.add_argument("--n-predict", "-n", type=int, default=12, help="Üretilecek maksimum token sayısı")
    parser.add_argument("--temperature", "-t", type=float, default=0.2, help="Üretim sıcaklığı")
    parser.add_argument("--simulate", "-s", action="store_true", help="llama-server yokken simüle token akışı ile test et")
    parser.add_argument("--play", "-p", action="store_true", help="Üretilen sesi yerel hoparlörde çal (varsa)")
    args = parser.parse_args()

    run_benchmark(
        user_query=args.query,
        base_url=args.url,
        n_predict=args.n_predict,
        temperature=args.temperature,
        simulate=args.simulate,
        play_audio=args.play,
    )


if __name__ == "__main__":
    main()
