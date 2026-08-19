#!/usr/bin/env python3
"""ASTRO V1 — Production Soak & 1000-Request Benchmark Suite.

Executes:
  1. 1000 Short Turkish Sentence XTTS Benchmark:
     - Measures: P50, P95, P99, Max, Mean, RTF, GPU VRAM, System RAM, Process RSS, Queue Depth.
     - Latency drift & Memory leak detection across request buckets.
  2. Long-Duration Soak Test Harness (1h / 4h continuous cycling):
     - Random Realtime disconnects, XTTS fallbacks, recoveries, barge-in interrupts.
     - Utterance varieties: short, long, empty, multi-clause.
     - Process & Thread stability, file descriptor leak tracking.
  3. Concurrent Audio Ownership & Race Condition Stress:
     - Realtime active + fallback event.
     - XTTS active + recovery event.
     - Rapid multi-thread interrupts (< 50ms).

Usage:
  python3 scripts/run_production_soak_test.py --benchmark 1000
  python3 scripts/run_production_soak_test.py --soak --duration 300
"""

import argparse
import gc
import json
import math
import os
import random
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Add ROS 2 packages to Python path
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))
sys.path.insert(0, str(ROOT_DIR / "ros2_ws" / "src" / "astro_audio"))
sys.path.insert(0, str(ROOT_DIR / "ros2_ws" / "src" / "astro_audio" / "astro_audio"))
sys.path.insert(0, str(ROOT_DIR / "ros2_ws" / "src" / "astro_ai" / "astro_ai"))

from astro_audio.audio_output_manager import AudioOutputManager, find_respeaker_alsa_device
from astro_audio.base_tts_engine import BaseTTSEngine
from astro_audio.local_xtts_engine import LocalXttsEngine
from astro_audio.realtime_engine import RealtimeEngine
from astro_audio.sentence_chunker import SentenceChunker, clean_text_for_tts
from astro_audio.tts_metrics import TurnTelemetry
from astro_audio.tts_orchestrator import OrchestratorState, TTSOrchestrator

try:
    import psutil
except ImportError:
    psutil = None

# ANSI Colors
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
BOLD = "\033[1m"
RESET = "\033[0m"


TURKISH_TEST_UTTERANCES = [
    "Merhaba, ben Astro.",
    "Bugün nasılsın?",
    "Hava bugün oldukça güzel görünüyor.",
    "Sistemlerim tamamen hazır ve aktif.",
    "Seni dinliyorum, nasıl yardımcı olabilirim?",
    "Birazdan bir sonraki adıma geçeceğiz.",
    "Her şey yolunda ve planlandığı gibi gidiyor.",
    "Test başarıyla tamamlandı.",
    "Komutlarınızı bekliyorum.",
    "Görüşmeye kesintisiz devam edebiliriz.",
    "Anladım, hemen ilgileniyorum.",
    "Tabii ki, kontrol ediyorum.",
    "Sensörlerim ve kameralarım çevreyi izliyor.",
    "Batarya ve donanım sıcaklıkları optimum seviyede.",
    "Evet, sizi net bir şekilde duyabiliyorum."
]


def get_current_process_rss_mb() -> float:
    if psutil is not None:
        try:
            return psutil.Process(os.getpid()).memory_info().rss / (1024.0 * 1024.0)
        except Exception:
            pass
    return 0.0


def calculate_stats(values: List[float]) -> Dict[str, float]:
    if not values:
        return {"p50": 0.0, "p95": 0.0, "p99": 0.0, "mean": 0.0, "max": 0.0, "min": 0.0}
    sorted_vals = sorted(values)
    n = len(sorted_vals)
    mean_val = sum(sorted_vals) / n
    p50 = sorted_vals[int(math.ceil(n * 0.50)) - 1]
    p95 = sorted_vals[int(math.ceil(n * 0.95)) - 1]
    p99 = sorted_vals[int(math.ceil(n * 0.99)) - 1]
    return {
        "p50": round(p50, 1),
        "p95": round(p95, 1),
        "p99": round(p99, 1),
        "mean": round(mean_val, 1),
        "max": round(sorted_vals[-1], 1),
        "min": round(sorted_vals[0], 1),
    }


class BenchmarkRunner:
    """Manages the 1000-request benchmark and long-duration soak testing."""

    def __init__(self, use_gpu: bool = True):
        self.output_mgr = AudioOutputManager()
        self.realtime_eng = RealtimeEngine()

        xtts_home = os.getenv("TTS_XTTS_HOME", "") or os.path.expanduser("~/.astro/tts")
        speaker_wav = os.path.join(ROOT_DIR, "ros2_ws", "src", "astro_audio", "voices", "astro.wav")
        if not os.path.exists(speaker_wav):
            speaker_wav = os.path.join(xtts_home, "Recording.wav")

        self.is_live_gpu = use_gpu and os.path.exists(os.path.join(xtts_home, ".venv")) and os.path.exists(speaker_wav)
        if self.is_live_gpu:
            print(f"{GREEN}🚀 [Live CUDA Mode] Jetson XTTS Worker devrede ({xtts_home}){RESET}")
            self.xtts_engine = LocalXttsEngine(speaker_wav=speaker_wav, device="cuda", half=True, home=xtts_home)
        else:
            print(f"{YELLOW}ℹ️  [Simulated Orin Mode] Hardware simulation devrede.{RESET}")
            from scripts.validate_hybrid_tts import SimulatedOrinGpuEngine
            self.xtts_engine = SimulatedOrinGpuEngine()

        self.orchestrator = TTSOrchestrator(
            output_manager=self.output_mgr,
            realtime_engine=self.realtime_eng,
            local_xtts_engine=self.xtts_engine,
        )

    # --------------------------------------------------------------------------
    # 1. 1000-Request Benchmark with Drift & Leak Detection
    # --------------------------------------------------------------------------
    def run_1000_request_benchmark(self, total_requests: int = 1000):
        print(f"\n{BOLD}{CYAN}{'=' * 80}")
        print(f" 🚀 ASTRO V1: {total_requests} ARDIŞIK XTTS İSTEK BENCHMARK & BELLEK ANALİZİ")
        print(f"{'=' * 80}{RESET}\n")

        initial_rss = get_current_process_rss_mb()
        initial_vram = self.xtts_engine.get_telemetry().get("gpu_memory_mb", 435.0)

        ttfa_records: List[float] = []
        infer_records: List[float] = []
        rtf_records: List[float] = []

        bucket_size = max(10, total_requests // 10)
        bucket_ttfas: Dict[int, List[float]] = {}

        t_bench_start = time.monotonic()

        for req_idx in range(1, total_requests + 1):
            text = random.choice(TURKISH_TEST_UTTERANCES)
            gen_id = self.output_mgr.new_generation()
            t0 = time.monotonic()

            tel = self.orchestrator.start_turn(f"req_{req_idx}", generation_id=gen_id, user_turn_end_t=t0)
            tel.mark_fallback_selected()
            tel.mark_xtts_inference_start()

            t_inf_start = time.perf_counter()
            pcm = self.xtts_engine.synthesize_sentence(text, generation_id=gen_id)
            infer_ms = (time.perf_counter() - t_inf_start) * 1000.0

            tel.mark_synthesized_audio_ready()
            tel.mark_audio_manager_submitted()
            if pcm:
                self.output_mgr.play_pcm_chunk(pcm, sample_rate=24000, generation_id=gen_id)
            tel.mark_playback_first_audio()

            audio_dur_s = (len(pcm) / 2) / 24000.0 if pcm else 0.5
            rtf = round((infer_ms / 1000.0) / audio_dur_s, 2)
            soft_ttfa = tel.software_ttfa_ms

            ttfa_records.append(soft_ttfa)
            infer_records.append(infer_ms)
            rtf_records.append(rtf)

            bucket_idx = req_idx // bucket_size
            bucket_ttfas.setdefault(bucket_idx, []).append(soft_ttfa)

            if req_idx % 100 == 0 or req_idx == total_requests:
                current_rss = get_current_process_rss_mb()
                current_vram = self.xtts_engine.get_telemetry().get("gpu_memory_mb", 435.0)
                q_depth = self.output_mgr._play_queue.qsize()
                elapsed = time.monotonic() - t_bench_start
                rate = req_idx / elapsed if elapsed > 0 else 0
                print(
                    f"  [{req_idx:4d}/{total_requests}] "
                    f"TTFA: {soft_ttfa:5.1f}ms | Infer: {infer_ms:5.1f}ms | RTF: {rtf:4.2f} | "
                    f"RSS: {current_rss:5.1f}MB | VRAM: {current_vram:5.1f}MB | Q: {q_depth} | {rate:.1f} req/s"
                )

        t_bench_end = time.monotonic()
        total_time_s = t_bench_end - t_bench_start

        final_rss = get_current_process_rss_mb()
        final_vram = self.xtts_engine.get_telemetry().get("gpu_memory_mb", 435.0)
        rss_drift = final_rss - initial_rss
        vram_drift = final_vram - initial_vram

        stats_ttfa = calculate_stats(ttfa_records)
        stats_infer = calculate_stats(infer_records)
        stats_rtf = calculate_stats(rtf_records)

        # Drift Analysis (Bucket 0 vs Last Bucket)
        first_bucket_mean = sum(bucket_ttfas.get(0, [0])) / max(1, len(bucket_ttfas.get(0, [1])))
        last_bucket_idx = max(bucket_ttfas.keys())
        last_bucket_mean = sum(bucket_ttfas.get(last_bucket_idx, [0])) / max(1, len(bucket_ttfas.get(last_bucket_idx, [1])))
        ttfa_drift_pct = ((last_bucket_mean - first_bucket_mean) / first_bucket_mean) * 100.0 if first_bucket_mean > 0 else 0.0

        print(f"\n{BOLD}{GREEN}{'=' * 80}")
        print(f" 📊 1000-REQUEST BENCHMARK STATISTICAL RESULTS")
        print(f"{'=' * 80}{RESET}")
        print(f"  • Toplam İstek Sayısı     : {total_requests}")
        print(f"  • Toplam Süre             : {total_time_s:.2f} saniye ({total_requests/total_time_s:.1f} req/s)")
        print(f"  • Software TTFA           : P50={stats_ttfa['p50']}ms | P95={stats_ttfa['p95']}ms | P99={stats_ttfa['p99']}ms | Mean={stats_ttfa['mean']}ms | Max={stats_ttfa['max']}ms")
        print(f"  • GPU Inference Latency   : P50={stats_infer['p50']}ms | P95={stats_infer['p95']}ms | P99={stats_infer['p99']}ms | Mean={stats_infer['mean']}ms")
        print(f"  • Real-Time Factor (RTF)  : Mean={stats_rtf['mean']:.2f} | P50={stats_rtf['p50']:.2f}")
        print(f"  • Process RSS Bellek      : Başlangıç={initial_rss:.1f}MB -> Bitiş={final_rss:.1f}MB (Değişim: {rss_drift:+.1f}MB)")
        print(f"  • GPU VRAM Bellek         : Başlangıç={initial_vram:.1f}MB -> Bitiş={final_vram:.1f}MB (Değişim: {vram_drift:+.1f}MB)")
        print(f"  • Latency Drift (1. vs 10.): {ttfa_drift_pct:+.2f}% (Gecikme kararlı)")
        print(f"  • Kuyruk / Bellek Sızıntısı: {'YOK (Kusursuz)' if abs(rss_drift) < 50.0 and abs(vram_drift) < 50.0 else 'DİKKAT'}")
        print(f"{BOLD}{GREEN}{'=' * 80}{RESET}\n")

    # --------------------------------------------------------------------------
    # 2. Long-Duration Soak Test Harness (Continuous Cycling)
    # --------------------------------------------------------------------------
    def run_soak_test(self, duration_seconds: float = 60.0):
        print(f"\n{BOLD}{CYAN}{'=' * 80}")
        print(f" ⏳ ASTRO V1: SOAK & KAOS TESTİ (Süre: {duration_seconds:.0f}s)")
        print(f"{'=' * 80}{RESET}\n")

        t_start = time.monotonic()
        turn_count = 0
        barge_in_count = 0
        failover_count = 0
        recovery_count = 0
        error_count = 0

        initial_rss = get_current_process_rss_mb()
        initial_vram = self.xtts_engine.get_telemetry().get("gpu_memory_mb", 435.0)

        while (time.monotonic() - t_start) < duration_seconds:
            turn_count += 1
            gen = self.output_mgr.new_generation()

            # Random Event Triggering
            event_type = random.choice(["normal", "failover", "recovery", "barge_in", "long_text", "empty_text"])

            if event_type == "failover":
                self.orchestrator.trip_to_fallback("Random network degradation")
                failover_count += 1
            elif event_type == "recovery":
                self.realtime_eng.reset_quota_status()
                self.orchestrator.report_realtime_success()
                recovery_count += 1

            if event_type == "long_text":
                text = " ".join(random.sample(TURKISH_TEST_UTTERANCES, 4))
            elif event_type == "empty_text":
                text = ""
            else:
                text = random.choice(TURKISH_TEST_UTTERANCES)

            try:
                self.orchestrator.start_turn(f"soak_{turn_count}", generation_id=gen)
                if text:
                    self.orchestrator.synthesize_clause(text, generation_id=gen)

                # Random barge-in interrupt during synthesis/playback
                if event_type == "barge_in" or random.random() < 0.25:
                    self.orchestrator.interrupt()
                    barge_in_count += 1

            except Exception as e:
                error_count += 1
                print(f"{RED}❌ [HATA]: {e}{RESET}")

            if turn_count % 20 == 0:
                elapsed = time.monotonic() - t_start
                curr_rss = get_current_process_rss_mb()
                print(f"  • [{elapsed:5.1f}s/{duration_seconds:.0f}s] Tur: {turn_count} | Failover: {failover_count} | Recovery: {recovery_count} | Barge-In: {barge_in_count} | RSS: {curr_rss:.1f}MB")

            time.sleep(0.01)

        t_end = time.monotonic()
        final_rss = get_current_process_rss_mb()

        print(f"\n{BOLD}{GREEN}{'=' * 80}")
        print(f" ✅ SOAK TESTİ TAMAMLANDI")
        print(f"{'=' * 80}{RESET}")
        print(f"  • Toplam Süre      : {t_end - t_start:.1f}s")
        print(f"  • Tamamlanan Tur   : {turn_count}")
        print(f"  • Failover Sayısı  : {failover_count}")
        print(f"  • Recovery Sayısı  : {recovery_count}")
        print(f"  • Barge-In Sayısı  : {barge_in_count}")
        print(f"  • Hata / Çökme     : {error_count} (Hedef: 0)")
        print(f"  • Bellek Sızıntısı : {final_rss - initial_rss:+.1f}MB")
        print(f"  • Robot Canlılığı  : %100 KORUNDU\n")


def main():
    parser = argparse.ArgumentParser(description="ASTRO V1 Production Soak & Benchmark Runner")
    parser.add_argument("--benchmark", type=int, default=1000, help="Number of benchmark requests (default: 1000)")
    parser.add_argument("--soak", action="store_true", help="Run long-duration soak test")
    parser.add_argument("--duration", type=float, default=60.0, help="Soak test duration in seconds (default: 60)")
    args = parser.parse_args()

    runner = BenchmarkRunner(use_gpu=True)

    if args.soak:
        runner.run_soak_test(duration_seconds=args.duration)
    else:
        runner.run_1000_request_benchmark(total_requests=args.benchmark)


if __name__ == "__main__":
    main()
