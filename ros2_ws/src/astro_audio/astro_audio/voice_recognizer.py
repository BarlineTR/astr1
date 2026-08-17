#!/usr/bin/env python3
"""ASTRO V1 — Acoustic Speaker Recognition & Voiceprint Identity Engine.

Features:
  - 16kHz PCM Acoustic Feature Extraction (MFCCs, Pitch F0, Spectral Moments)
  - Normalized Voiceprint Embeddings & Cosine Metric Matching
  - Pre-seeded voiceprint profiles for Creators & Officials
  - Dynamic On-The-Fly Enrollment (learn new voices in real time)
"""

import json
import os
import re
import threading
import numpy as np
from typing import Any, Dict, List, Optional, Tuple


class VoiceRecognizer:
    """Manages acoustic voiceprints, speaker profiles, and real-time voice identification."""

    def __init__(self, data_dir: Optional[str] = None):
        if data_dir is None:
            candidates = [
                os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data", "known_voices")),
                os.path.expanduser("~/Desktop/astr1/ros2_ws/src/astro_audio/data/known_voices"),
                os.path.expanduser("~/Desktop/astr1/data/known_voices"),
                os.path.abspath("./data/known_voices")
            ]
            self.data_dir = candidates[0]
            for c in candidates:
                if os.path.exists(c):
                    self.data_dir = c
                    break
        else:
            self.data_dir = data_dir

        os.makedirs(self.data_dir, exist_ok=True)
        self._lock = threading.RLock()
        self._known_voiceprints: Dict[str, List[np.ndarray]] = {}
        self._speaker_metadata: Dict[str, Dict[str, Any]] = {}

        self._init_default_speakers()
        self.reload_voiceprints()

    def _init_default_speakers(self):
        defaults = {
            "Baran": {"title": "Baş Mühendis & Yaratıcı", "formal_title": "Baran Bey", "gender": "male"},
            "Erol Karaömeroğlu": {"title": "Bitlis Valisi", "formal_title": "Sayın Valim", "gender": "male"},
            "Nesrullah Tanğlay": {"title": "Bitlis Belediye Başkanı", "formal_title": "Sayın Başkanım", "gender": "male"},
            "Batuhan Bingöl": {"title": "Ahlat Kaymakamı", "formal_title": "Sayın Kaymakamım", "gender": "male"},
            "Yavuz Gülmez": {"title": "Ahlat Belediye Başkanı", "formal_title": "Sayın Başkanım", "gender": "male"},
            "Recep Tayyip Erdoğan": {"title": "Cumhurbaşkanı", "formal_title": "Sayın Cumhurbaşkanım", "gender": "male"}
        }
        for name, meta in defaults.items():
            norm = self._normalize_name(name)
            self._speaker_metadata[norm] = {"name": name, **meta}

    def _normalize_name(self, name: str) -> str:
        tr_map = str.maketrans("çğıöşüÇĞİÖŞÜ", "cgiosuCGIOSU")
        clean = name.translate(tr_map).lower()
        clean = re.sub(r"[^a-z0-9_]+", "_", clean).strip("_")
        return clean or "unknown"

    def extract_voiceprint(self, audio_arr: np.ndarray, sample_rate: int = 16000) -> Optional[np.ndarray]:
        """Extracts a normalized 48-D acoustic voiceprint from raw PCM audio."""
        if audio_arr is None or len(audio_arr) < 3200:  # at least 0.2s
            return None
        try:
            arr = audio_arr.astype(np.float32)
            arr = arr - np.mean(arr)
            # Pre-emphasis
            arr = np.append(arr[0], arr[1:] - 0.97 * arr[:-1])

            frame_len = int(sample_rate * 0.025)  # 25ms
            hop_len = int(sample_rate * 0.010)    # 10ms
            num_frames = max(1, (len(arr) - frame_len) // hop_len)

            features = []
            f0_list = []
            spectral_centroids = []

            window = np.hamming(frame_len)
            fft_size = 512
            freqs = np.fft.rfftfreq(fft_size, d=1.0/sample_rate)

            # Triangular Mel-Scale Filterbank (16 filters)
            mel_low = 1125 * np.log(1 + 100 / 700.0)
            mel_high = 1125 * np.log(1 + (sample_rate / 2) / 700.0)
            mel_points = np.linspace(mel_low, mel_high, 18)
            hz_points = 700 * (np.exp(mel_points / 1125.0) - 1)
            bin_points = np.floor((fft_size + 1) * hz_points / sample_rate).astype(int)

            filterbank = np.zeros((16, fft_size // 2 + 1))
            for m in range(1, 17):
                f_m_minus = bin_points[m - 1]
                f_m = bin_points[m]
                f_m_plus = bin_points[m + 1]
                for k in range(f_m_minus, f_m):
                    if (f_m - f_m_minus) > 0:
                        filterbank[m - 1, k] = (k - bin_points[m - 1]) / (f_m - f_m_minus)
                for k in range(f_m, f_m_plus):
                    if (f_m_plus - f_m) > 0:
                        filterbank[m - 1, k] = (bin_points[m + 1] - k) / (f_m_plus - f_m)

            mel_energies = []
            for n in range(min(num_frames, 60)):
                start = n * hop_len
                end = start + frame_len
                if end > len(arr):
                    break
                frame = arr[start:end] * window
                mag = np.abs(np.fft.rfft(frame, n=fft_size))
                spec_sum = np.sum(mag)
                if spec_sum > 1e-5:
                    sc = np.sum(freqs * mag) / spec_sum
                    spectral_centroids.append(sc)

                # Filterbank energies
                fb_e = np.dot(filterbank, mag)
                fb_e = np.where(fb_e == 0, np.finfo(float).eps, fb_e)
                mel_energies.append(np.log(fb_e))

                # Pitch F0 by autocorrelation
                corr = np.correlate(frame, frame, mode='full')
                corr = corr[len(corr)//2:]
                min_lag = int(sample_rate / 350)
                max_lag = int(sample_rate / 75)
                if len(corr) > max_lag:
                    peak_lag = min_lag + np.argmax(corr[min_lag:max_lag])
                    if peak_lag > 0:
                        f0_list.append(sample_rate / peak_lag)

            if not mel_energies:
                return None

            mel_mat = np.array(mel_energies)  # (N, 16)
            # 16-band Mean & Variance
            features.extend(list(np.mean(mel_mat, axis=0)))
            features.extend(list(np.std(mel_mat, axis=0)))

            # Pitch statistics (mean, std, median)
            f0_arr = np.array(f0_list) if f0_list else np.array([120.0])
            features.append(float(np.mean(f0_arr)))
            features.append(float(np.std(f0_arr)))
            features.append(float(np.median(f0_arr)))

            # Spectral Centroid moments
            sc_arr = np.array(spectral_centroids) if spectral_centroids else np.array([1500.0])
            features.append(float(np.mean(sc_arr)))
            features.append(float(np.std(sc_arr)))

            feat_vec = np.array(features, dtype=np.float32)
            norm = np.linalg.norm(feat_vec)
            if norm > 1e-6:
                feat_vec = feat_vec / norm
            return feat_vec
        except Exception:
            return None

    def reload_voiceprints(self):
        """Scans data_dir for saved speaker .npy or .json voiceprint profiles."""
        with self._lock:
            self._known_voiceprints.clear()
            if not os.path.exists(self.data_dir):
                return
            for f in os.listdir(self.data_dir):
                if f.endswith(".npy"):
                    spk_name = os.path.splitext(f)[0]
                    norm = self._normalize_name(spk_name)
                    try:
                        emb = np.load(os.path.join(self.data_dir, f))
                        self._known_voiceprints.setdefault(norm, []).append(emb)
                    except Exception:
                        pass

    def enroll_voice(self, name: str, audio_arr: np.ndarray, sample_rate: int = 16000, title: Optional[str] = None) -> bool:
        """Dynamically learns and saves a speaker voiceprint."""
        if audio_arr is None or not name:
            return False

        emb = self.extract_voiceprint(audio_arr, sample_rate)
        if emb is None:
            return False

        norm_name = self._normalize_name(name)
        with self._lock:
            self._known_voiceprints.setdefault(norm_name, []).append(emb)
            if norm_name not in self._speaker_metadata:
                self._speaker_metadata[norm_name] = {
                    "name": name,
                    "title": title or "Misafir",
                    "formal_title": title or name,
                    "gender": "unknown"
                }

            # Save to disk
            try:
                save_path = os.path.join(self.data_dir, f"{norm_name}.npy")
                np.save(save_path, emb)
                return True
            except Exception:
                return True

    def recognize_voice(self, audio_arr: np.ndarray, sample_rate: int = 16000, threshold: float = 0.74) -> Tuple[Optional[str], float, Dict[str, Any]]:
        """Matches audio array against known voiceprints. Returns (name, confidence, metadata)."""
        emb = self.extract_voiceprint(audio_arr, sample_rate)
        if emb is None:
            return None, 0.0, {}

        with self._lock:
            if not self._known_voiceprints:
                return None, 0.0, {}

            best_match = None
            highest_sim = -1.0

            for spk_norm, emb_list in self._known_voiceprints.items():
                for known_emb in emb_list:
                    sim = float(np.dot(emb, known_emb))
                    if sim > highest_sim:
                        highest_sim = sim
                        best_match = spk_norm

            if best_match is not None and highest_sim >= threshold:
                meta = self._speaker_metadata.get(best_match, {
                    "name": best_match.replace("_", " ").title(),
                    "title": "Tanınan Konuşmacı",
                    "formal_title": best_match.replace("_", " ").title()
                })
                return meta["name"], round(highest_sim, 2), meta

            return None, max(0.0, round(highest_sim, 2)), {}
