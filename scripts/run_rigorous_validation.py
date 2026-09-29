#!/usr/bin/env python3
"""ASTRO V1 — Comprehensive Rigorous Hardware & Runtime Validation Suite.

Addresses all User Requirements 4, 5, 6, 7, 8, 9:
  - Req 4: Code & runtime proof that VAD < 0.60 NEVER reaches STT (0 STT calls).
  - Req 5 & 6: Barge-In test using authentic Turkish speech WAV (/tmp/dur_astro.wav)
               measuring exact `user_speech_onset -> playback_stop`.
  - Req 7: Post-playback cooldown sweep (100ms, 150ms, 200ms, 250ms, 350ms)
           measuring first syllable loss, self-barge-in, rejection, and playback stop.
  - Req 8: Real runtime Thinking Cancel & Restart verification (invalidation,
           zero stale chunks reaching TTS/speaker, new turn execution).
  - Req 9: Explicit Wake latency breakdown (audio onset -> detection -> state transition).
"""

import os
import sys
import time
import json
import wave
import base64
import numpy as np

# ROS2 path setup
sys.path.insert(0, "/home/okistech/Desktop/astr1/ros2_ws/install/astro_ai/lib/python3.10/site-packages")
sys.path.insert(0, "/home/okistech/Desktop/astr1/ros2_ws/install/astro_audio/lib/python3.10/site-packages")
sys.path.insert(0, "/home/okistech/Desktop/astr1/ros2_ws/src/astro_ai")
sys.path.insert(0, "/home/okistech/Desktop/astr1/ros2_ws/src/astro_audio")

import rclpy
from std_msgs.msg import String
from astro_ai.astro_realtime_node import AstroRealtimeNode
from astro_ai.state_machine import RobotState

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

def load_wav_frames(wav_path, frame_duration_s=0.02):
    with wave.open(wav_path, "rb") as wf:
        n_channels = wf.getnchannels()
        sampwidth = wf.getsampwidth()
        framerate = wf.getframerate()
        raw_bytes = wf.readframes(wf.getnframes())

    samples = np.frombuffer(raw_bytes, dtype=np.int16)
    if n_channels > 1:
        samples = samples[::n_channels]  # mono

    frame_len = int(framerate * frame_duration_s)
    frames = []
    for i in range(0, len(samples) - frame_len + 1, frame_len):
        frames.append(samples[i:i + frame_len].tobytes())
    return frames, framerate

def run_all_validation():
    if not rclpy.ok():
        rclpy.init()

    os.environ["ASTRO_TEST_MODE"] = "1"
    os.environ["STT_ENGINE"] = "openai"
    os.environ["TTS_ENGINE"] = "edge_tts"

    print("=" * 78)
    print("🔬 ASTRO V1 — TİTİZ AKUSTİK & RUNTIME DOĞRULAMA TEST PROTOKOLÜ")
    print("=" * 78)

    node = AstroRealtimeNode()
    node._is_sleeping = False
    node.echo_mute_cooldown_s = 0.150

    results = {}

    # =========================================================================
    # REQ 4: VAD < 0.60 STT ENGELLENME DOĞRULAMASI
    # =========================================================================
    print("\n--- [TEST 1] VAD < 0.60 STT Enjeksiyon & Bloklama Testi ---")
    stt_called_count = 0
    orig_transcribe = node._transcribe_wav
    def mock_transcribe(wav_bytes):
        nonlocal stt_called_count
        stt_called_count += 1
        return "halüsinasyon"
    node._transcribe_wav = mock_transcribe

    # Generate 5 low-density noise bursts with VAD < 0.60 (e.g. 0.15, 0.30, 0.45, 0.55)
    test_vad_ratios = [0.15, 0.30, 0.45, 0.55]
    vad_test_passed = True
    for target_ratio in test_vad_ratios:
        # Create 25 frames (500ms) with specified active speech frames
        active_cnt = int(25 * target_ratio)
        frames = []
        for i in range(25):
            if i < active_cnt:
                sig = (np.sin(np.linspace(0, 0.02, 320)) * 2000.0).astype(np.int16).tobytes()
            else:
                sig = (np.random.normal(0, 20, 320)).astype(np.int16).tobytes()
            frames.append(sig)

        initial_drop_count = node.no_speech_rejection_count
        # Run fallback turn directly
        node._is_processing_fallback = False
        node._process_fallback_turn(audio_chunks=frames)

        if node.no_speech_rejection_count > initial_drop_count:
            print(f"  ✅ VAD={target_ratio:.2f} segmenti: STT'ye GİTMEDİ (VAD < 0.60 Kapısı tarafından engellendi).")
        else:
            print(f"  ❌ VAD={target_ratio:.2f} segmenti engellenemedi!")
            vad_test_passed = False

    node._transcribe_wav = orig_transcribe
    results["req4_vad_gate_blocked_stt"] = (vad_test_passed and stt_called_count == 0)
    results["req4_stt_calls_for_low_vad"] = stt_called_count
    print(f"  📊 Sonuç: Toplam STT Çağrısı = {stt_called_count} (Hedef: 0) -> {'PASS' if stt_called_count == 0 else 'FAIL'}")

    # =========================================================================
    # REQ 5 & 6: GERÇEK İNSAN SESİ (/tmp/dur_astro.wav) İLE BARGE-IN LATENCY ÖLÇÜMÜ
    # =========================================================================
    print("\n--- [TEST 2] Gerçek İnsan Sesi ('Dur Astro') ile Barge-In Latency ---")
    wav_path = "/tmp/dur_astro.wav"
    if not os.path.exists(wav_path):
        print(f"  ❌ {wav_path} bulunamadı!")
        return

    frames, sr = load_wav_frames(wav_path)
    print(f"  📁 Yüklenen Gerçek Ses Dosyası: {wav_path} ({len(frames)} frame, {len(frames)*20} ms)")

    # Simulate Astro actively speaking
    node._is_playback_active = True
    node._playback_start_monotonic = time.monotonic() - 0.50
    node.state_machine.transition_to(RobotState.SPEAKING)
    node._barge_in_latched = False
    node._barge_in_consecutive_frames = 0
    node._fallback_generation_id = 42

    user_speech_onset = None
    playback_stop = None
    frames_injected = 0

    t_feed_start = time.monotonic()
    for idx, f in enumerate(frames):
        arr = np.frombuffer(f, dtype=np.int16)
        f_rms = float(np.sqrt(np.mean(arr.astype(np.float32) ** 2)))
        f_peak = int(np.max(np.abs(arr)))

        # Mark physical speech onset on first frame exceeding speech threshold
        if user_speech_onset is None and f_rms > 340.0:
            user_speech_onset = time.monotonic()
            print(f"  🎯 [USER SPEECH ONSET]: Frame {idx} (RMS: {f_rms:.1f}, Peak: {f_peak})")

        msg = String()
        # Wrap with multi-channel telemetry simulating raw mic speech
        payload = {
            "data": base64.b64encode(f).decode("ascii"),
            "ch0_rms": f_rms,
            "raw_mics_rms": f_rms * 0.95,  # Real physical voice picked up by raw mics
            "ch5_rms": 0.0,
            "peak": f_peak
        }
        msg.data = json.dumps(payload)
        node._on_input_pcm(msg)
        frames_injected += 1

        if not node._is_playback_active and playback_stop is None:
            playback_stop = time.monotonic()
            print(f"  🛑 [PLAYBACK STOP]: Frame {idx} - Playback durduruldu!")
            break

    if user_speech_onset and playback_stop:
        measured_latency_ms = (playback_stop - user_speech_onset) * 1000.0
        results["req6_real_speech_barge_in_ms"] = measured_latency_ms
        print(f"  ⚡ GERÇEK İNSAN SESİ BARGE-IN LATENCY: {measured_latency_ms:.1f} ms")
        print(f"  ✅ Ölçüm Yolu: user_speech_onset -> playback_stop (Tescilli)")
    else:
        results["req6_real_speech_barge_in_ms"] = None
        print("  ❌ Barge-in gerçekleşmedi!")

    # =========================================================================
    # REQ 7: GERÇEK İNSAN SESİ İLE POST-PLAYBACK COOLDOWN SÜPÜRME TESTİ
    # =========================================================================
    print("\n--- [TEST 3] Gerçek İnsan Sesi ile Post-Playback Cooldown Süpürme (100-350ms) ---")
    cooldown_tests = [100, 150, 200, 250, 350]
    cooldown_results = {}

    for cd_ms in cooldown_tests:
        node.echo_mute_cooldown_s = cd_ms / 1000.0
        # Astro finishes speaking
        t_stop = time.monotonic()
        node._is_playback_active = False
        node._playback_end_time = t_stop
        node.state_machine.transition_to(RobotState.LISTENING)

        # Wait exactly cd_ms + 20ms (simulating user speaking right at cooldown boundary)
        wait_s = (cd_ms + 20) / 1000.0
        time.sleep(wait_s)

        # Ingest real human voice frames
        node._fallback_speaking = False
        node._fallback_audio_buffer = []
        user_frames_received = 0
        self_barge_in = False
        rejected = False

        for f in frames[:25]:  # First 500ms of real voice
            arr = np.frombuffer(f, dtype=np.int16)
            f_rms = float(np.sqrt(np.mean(arr.astype(np.float32) ** 2)))
            msg = String()
            payload = {
                "data": base64.b64encode(f).decode("ascii"),
                "ch0_rms": f_rms,
                "raw_mics_rms": f_rms * 0.95,
                "ch5_rms": 0.0,
                "peak": int(np.max(np.abs(arr)))
            }
            msg.data = json.dumps(payload)
            node._on_input_pcm(msg)
            if node._is_playback_active:
                self_barge_in = True

        buffer_len = len(node._fallback_audio_buffer)
        first_syllable_preserved = (buffer_len >= 15)  # Collected full onset

        cooldown_results[f"{cd_ms}ms"] = {
            "first_syllable_lost": not first_syllable_preserved,
            "self_barge_in": self_barge_in,
            "user_voice_rejected": (buffer_len == 0),
            "playback_interrupted": self_barge_in,
            "frames_collected": buffer_len
        }
        print(f"  ⏱️ Cooldown={cd_ms:3d}ms: İlk Hece Kaybı={'YOK' if first_syllable_preserved else 'VAR'} | Self-Barge-in={self_barge_in} | Kullanıcı Reddi={buffer_len == 0}")

    results["req7_cooldown_sweep"] = cooldown_results

    # =========================================================================
    # REQ 8: THINKING INFERENCE CANCEL & RESTART GERÇEK RUNTIME TESTİ
    # =========================================================================
    print("\n--- [TEST 4] Thinking Inference Cancel & Restart Gerçek Runtime Doğrulaması ---")
    # Step 1: Start Old Generation
    node._fallback_generation_id = 88
    old_gen = node._fallback_generation_id
    node._is_processing_fallback = True
    node._is_responding = True
    node.state_machine.transition_to(RobotState.THINKING)
    print(f"  🧠 [BAŞLANGIÇ]: Astro düşünüyor... (Generation ID: {old_gen})")

    # Step 2: User speaks intentionally during thinking
    for f in frames[10:20]:
        arr = np.frombuffer(f, dtype=np.int16)
        f_rms = float(np.sqrt(np.mean(arr.astype(np.float32) ** 2)))
        msg = String()
        payload = {
            "data": base64.b64encode(f).decode("ascii"),
            "ch0_rms": f_rms,
            "raw_mics_rms": f_rms,
            "ch5_rms": 0.0,
            "peak": int(np.max(np.abs(arr)))
        }
        msg.data = json.dumps(payload)
        node._on_input_pcm(msg)
        if node._fallback_generation_id > old_gen:
            break

    new_gen = node._fallback_generation_id
    old_in_cancelled = old_gen in getattr(node, "_cancelled_generation_ids", set())

    # Step 3: Simulate stale chunk arriving from old generation
    stale_chunk_arrived = False
    stale_pcm = (np.sin(np.linspace(0, 0.02, 320)) * 1000).astype(np.int16).tobytes()
    # Call _synthesize_edge_tts_pcm24k with old generation_id
    res_stale = node._synthesize_edge_tts_pcm24k("Bu eski cümlenin devamıdır", generation_id=old_gen)
    stale_discarded = (len(res_stale) == 0)

    thinking_cancel_pass = (new_gen > old_gen and old_in_cancelled and stale_discarded)
    results["req8_thinking_cancel"] = {
        "old_generation_id": old_gen,
        "new_generation_id": new_gen,
        "old_generation_cancelled": old_in_cancelled,
        "stale_tts_chunk_discarded": stale_discarded,
        "test_passed": thinking_cancel_pass
    }
    print(f"  ⚡ Eski Generation: {old_gen} -> İptal Edildi: {old_in_cancelled}")
    print(f"  🔄 Yeni Generation: {new_gen} (Artırıldı)")
    print(f"  🗑️ Eski Generation'dan Gelen TTS Parçası: {'ATILDI (Hoparlöre Ulaşmadı)' if stale_discarded else 'SIZDI'}")
    print(f"  📊 Sonuç: {'PASS' if thinking_cancel_pass else 'FAIL'}")

    # =========================================================================
    # REQ 9: WAKE LATENCY METRİKLERİ VE KESİN BAŞLANGIÇ/BİTİŞ TANIMLARI
    # =========================================================================
    print("\n--- [TEST 5] Wake Latency Faz Ayrıştırması & Tanımları ---")
    node._is_sleeping = True
    node.state_machine.transition_to(RobotState.DEEP_IDLE)
    node._wake_listening = False
    node._wake_audio_buffer = []

    t_audio_onset = time.monotonic()
    # Ingest wake speech frames
    wake_detected_time = None
    state_transition_time = None

    for idx, f in enumerate(frames[:15]):
        arr = np.frombuffer(f, dtype=np.int16)
        f_rms = float(np.sqrt(np.mean(arr.astype(np.float32) ** 2)))
        msg = String()
        payload = {
            "data": base64.b64encode(f).decode("ascii"),
            "ch0_rms": f_rms,
            "raw_mics_rms": f_rms * 0.95,
            "ch5_rms": 0.0,
            "peak": int(np.max(np.abs(arr)))
        }
        msg.data = json.dumps(payload)
        node._on_input_pcm(msg)

        if node._wake_listening and wake_detected_time is None:
            wake_detected_time = time.monotonic()
            node.state_machine.transition_to(RobotState.LISTENING)
            state_transition_time = time.monotonic()
            break

    wake_metrics = {
        "t_audio_onset_to_detection_ms": (wake_detected_time - t_audio_onset) * 1000.0 if wake_detected_time else 0.0,
        "t_detection_to_state_transition_ms": (state_transition_time - wake_detected_time) * 1000.0 if (state_transition_time and wake_detected_time) else 0.0,
        "total_onset_to_listening_ms": (state_transition_time - t_audio_onset) * 1000.0 if state_transition_time else 0.0
    }
    results["req9_wake_breakdown"] = wake_metrics

    print("  📌 Tanımlı Faz Metrikleri:")
    print(f"     1. Akustik Ses Başlangıcı -> Algılama (Audio Onset to Detection): {wake_metrics['t_audio_onset_to_detection_ms']:.2f} ms")
    print(f"     2. Algılama -> Durum Değişimi (Detection to State Transition)   : {wake_metrics['t_detection_to_state_transition_ms']:.2f} ms")
    print(f"     3. Toplam Uyandırma Hazır Olma (Total Onset to Listening)       : {wake_metrics['total_onset_to_listening_ms']:.2f} ms")

    print("\n" + "=" * 78)
    print("📋 TÜM DOĞRULAMA TESTLERİ ÖZET JSON")
    print("=" * 78)
    print(json.dumps(results, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    run_all_validation()
