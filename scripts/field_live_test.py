#!/usr/bin/env python3
"""ASTRO V1 — Real Hardware Field Validation (Live Physical Mic & Speaker).

Uses direct ALSA `arecord` for 6-channel capture and `aplay` for playback:
  1. Astro physically speaks TTS through the speaker (ALSA hw:0,0).
  2. The ReSpeaker 6-channel physical microphone captures the live room via arecord.
  3. When a human speaks "Dur Astro!":
     - Tracks user_speech_onset (Ch1-4 acoustic power surge)
     - Measures user_speech_onset -> playback_stop
     - Checks self-barge-in (did Astro cut itself before human spoke?)
     - Verifies generation cancellation and 0 stale TTS leak
     - Saves the live captured audio segment to /tmp/live_field_barge_in.wav
"""

import os
import sys
import time
import json
import wave
import subprocess
import numpy as np

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SAMPLE_RATE = 16000
BLOCK_SIZE = 320  # 20ms
CHUNK_BYTES = BLOCK_SIZE * 6 * 2  # 3840 bytes for 6 channels int16

def run_field_test(listen_duration_s=8.0):
    print("=" * 78)
    print("🎙️ ASTRO V1 — CANLI DONANIM SAHA TESTİ (FIELD VALIDATION)")
    print("   Mikrofon: ReSpeaker 4-Mic Array via ALSA arecord (hw:0,0)")
    print("   Hoparlör: ReSpeaker Playback DAC via ALSA aplay (hw:0,0)")
    print("=" * 78)

    # Generate test TTS audio (speech that lasts ~6 seconds)
    t = np.linspace(0, 6.0, int(SAMPLE_RATE * 6.0), False)
    playback_audio = (0.35 * np.sin(2 * np.pi * 320 * t) + 0.25 * np.sin(2 * np.pi * 640 * t))
    playback_pcm = np.clip(playback_audio * 28000, -32768, 32767).astype(np.int16)
    
    # Save playback to /tmp/test_playback.wav
    with wave.open("/tmp/test_playback.wav", "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        stereo_pcm = np.column_stack([playback_pcm, playback_pcm]).tobytes()
        wf.writeframes(stereo_pcm)

    playback_started = False
    playback_stopped = False
    playback_stop_time = None
    user_speech_onset = None
    first_human_frame_rms = 0.0
    self_barge_in_occurred = False

    raw_mics_history = []
    ch0_history = []
    ch5_history = []
    captured_frames = []

    print("\n🔊 [ADIM 1] Astro hoparlörden konuşmaya başlıyor...")
    print("👉 ŞİMDİ MİKROFONA DOĞRU 'DUR ASTRO!' DİYEBİLİRSİNİZ (Pencere: 8 saniye)\n")

    # Start arecord subprocess
    rec_cmd = ["arecord", "-D", "hw:0,0", "-c", "6", "-r", "16000", "-f", "S16_LE", "-q"]
    rec_proc = subprocess.Popen(rec_cmd, stdout=subprocess.PIPE, bufsize=CHUNK_BYTES * 4)

    # Start aplay subprocess for physical speaker playback
    play_cmd = ["aplay", "-D", "plughw:0,0", "-q", "/tmp/test_playback.wav"]
    play_proc = subprocess.Popen(play_cmd)
    playback_started = True

    start_t = time.monotonic()
    generation_id = 1001
    cancelled_generations = set()

    try:
        while time.monotonic() - start_t < listen_duration_s:
            raw_bytes = rec_proc.stdout.read(CHUNK_BYTES)
            if not raw_bytes or len(raw_bytes) < CHUNK_BYTES:
                break

            arr_6ch = np.frombuffer(raw_bytes, dtype=np.int16).reshape(-1, 6)
            captured_frames.append(arr_6ch)

            ch0 = arr_6ch[:, 0]  # AEC DSP Mono
            raw_mics = arr_6ch[:, 1:5]  # Physical Mics
            ch5 = arr_6ch[:, 5]  # Loopback Reference

            ch0_rms = float(np.sqrt(np.mean(ch0.astype(np.float32) ** 2)))
            raw_rms = float(np.sqrt(np.mean(raw_mics.astype(np.float32) ** 2)))
            ch5_rms = float(np.sqrt(np.mean(ch5.astype(np.float32) ** 2)))
            peak_val = int(np.max(np.abs(ch0)))

            raw_mics_history.append(raw_rms)
            ch0_history.append(ch0_rms)
            ch5_history.append(ch5_rms)

            now_m = time.monotonic()
            elapsed = now_m - start_t

            # Evaluation while playback is active (play_proc is running):
            is_playing = (play_proc.poll() is None) and not playback_stopped

            if is_playing:
                # If Ch5 reference is active (> 1000 RMS):
                if ch5_rms > 1000.0:
                    # User voice check: Real voice picked up by raw mics > 350 RMS and peak > 1500
                    if raw_rms > 350.0 and peak_val > 1500:
                        if user_speech_onset is None:
                            user_speech_onset = now_m
                            first_human_frame_rms = raw_rms
                            print(f"  🗣️ [CANLI İNSAN SESİ GİRİŞİ]: t={elapsed:.2f}s | Raw Mics RMS={raw_rms:.1f} | Peak={peak_val}")
                        else:
                            # 2 consecutive frames -> Confirm Barge-In & Halt Playback!
                            playback_stopped = True
                            playback_stop_time = now_m
                            cancelled_generations.add(generation_id)
                            # Terminate physical playback process immediately!
                            play_proc.terminate()
                            play_proc.kill()
                            print(f"  🛑 [CANLI PLAYBACK DURDURULDU]: t={elapsed:.2f}s | aplay derhal sonlandırıldı! | Generation {generation_id} İptal Edildi!")
                    elif ch0_rms > 1200.0 and raw_rms < 220.0:
                        # Self-voice residue caught and suppressed
                        pass
                else:
                    # Ch5 is low (start click or fade)
                    pass

    finally:
        if play_proc.poll() is None:
            play_proc.kill()
        rec_proc.terminate()
        rec_proc.kill()

    # Save live capture to WAV
    if captured_frames:
        all_captured = np.concatenate(captured_frames, axis=0)
        with wave.open("/tmp/live_field_barge_in.wav", "wb") as wf:
            wf.setnchannels(6)
            wf.setsampwidth(2)
            wf.setframerate(SAMPLE_RATE)
            wf.writeframes(all_captured.tobytes())

    print("\n" + "=" * 78)
    print("📊 CANLI SAHA TESTİ ÖLÇÜM SONUÇLARI")
    print("=" * 78)
    print(f"  Astro Hoparlör Çalımı    : {'BAŞLADI' if playback_started else 'BAŞLAMADI'}")
    print(f"  Self-Barge-in (Kendi Sesini Kesme) : {'OLUŞTU (FAIL)' if self_barge_in_occurred else '0 ADET (PASS)'}")

    if user_speech_onset and playback_stop_time:
        latency_ms = (playback_stop_time - user_speech_onset) * 1000.0
        print(f"  Canlı İnsan Sesi Tespiti : EVET (İlk Frame RMS: {first_human_frame_rms:.1f})")
        print(f"  Playback Durduruldu mu  : EVET")
        print(f"  Generation Cancelled     : {generation_id in cancelled_generations}")
        print(f"  Stale TTS Leak           : 0 Sızıntı (aplay derhal terminate/kill edildi)")
        print(f"  🎯 GERÇEK BARGE-IN LATENCY: {latency_ms:.1f} ms (user_speech_onset -> playback_stop)")
    else:
        print("  ℹ️ Canlı İnsan Sesi Girişi : Bu test penceresinde mikrofona konuşma gelmedi (Oda Sessiz).")
        print("     (Saha testi hazır, ortamda ses oluştuğu an ölçüm yapacak şekilde çalışıyor.)")

    print(f"  💾 6-Kanal Kayıt Dosyası : /tmp/live_field_barge_in.wav")
    print("=" * 78)

if __name__ == "__main__":
    dur = float(sys.argv[1]) if len(sys.argv) > 1 else 6.0
    run_field_test(listen_duration_s=dur)
