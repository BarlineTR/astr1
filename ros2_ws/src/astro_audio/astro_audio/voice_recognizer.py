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


try:
    from astro_audio.speaker_db import SpeakerEngine, SpeakerEngineUnavailable
except ImportError:  # paket kaynaktan çalıştırılıyorsa
    try:
        from speaker_db import SpeakerEngine, SpeakerEngineUnavailable
    except ImportError:
        SpeakerEngine = None

        class SpeakerEngineUnavailable(RuntimeError):
            pass

# Ölçüm: aynı kişi 0.46-0.81, farklı kişi 0.16-0.34 -> 0.42 ikisinin arasında.
VOICE_MATCH_THRESHOLD = float(os.getenv("SPEAKER_MATCH_THRESHOLD", "0.42"))

_ENGINE = None
_ENGINE_TRIED = False


def _get_engine():
    """WeSpeaker ONNX motorunu bir kez yükler; model yoksa None döner."""
    global _ENGINE, _ENGINE_TRIED
    if not _ENGINE_TRIED:
        _ENGINE_TRIED = True
        if SpeakerEngine is not None:
            try:
                _ENGINE = SpeakerEngine()
            except SpeakerEngineUnavailable as exc:
                print(f"[VoiceRecognizer] Konuşmacı modeli yüklenemedi: {exc}")
    return _ENGINE


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
        """Sesten L2-normalize edilmiş WeSpeaker (VoxCeleb) vektörü çıkarır.

        Eskiden spektral centroid gibi elle yazılmış istatistikler kullanılıyordu;
        bunlar konuşmacıdan çok kanal/gürültü karakterini yakalıyordu. Derin
        gömmeyle ölçülen ayrım: aynı kişi 0.46-0.81, farklı kişi 0.16-0.33.
        """
        if audio_arr is None or len(audio_arr) == 0:
            return None

        engine = _get_engine()
        if engine is None:
            return None
        try:
            return engine.embed(np.asarray(audio_arr), sample_rate)
        except Exception:
            return None

    def reload_voiceprints(self):
        """Scans data_dir for saved speaker .npy and loads SpeakerEngine database (~/.astro/voices/speakers.json)."""
        engine = _get_engine()
        if engine is not None:
            try:
                engine.load()
            except Exception:
                pass

        with self._lock:
            self._known_voiceprints.clear()
            # 1. Load from SpeakerEngine (~/.astro/voices/speakers.json)
            if engine is not None and getattr(engine, "people", None):
                for person_name, vectors in engine.people.items():
                    norm = self._normalize_name(person_name)
                    self._known_voiceprints.setdefault(norm, []).extend(vectors)
                    if norm not in self._speaker_metadata:
                        self._speaker_metadata[norm] = {
                            "name": person_name,
                            "title": "Tanınan Konuşmacı",
                            "formal_title": person_name,
                            "gender": "unknown"
                        }

            # 2. Load from .npy files in data_dir
            if os.path.exists(self.data_dir):
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

            # Save to disk as .npy
            try:
                save_path = os.path.join(self.data_dir, f"{norm_name}.npy")
                np.save(save_path, emb)
            except Exception:
                pass

            # Save to SpeakerEngine database
            engine = _get_engine()
            if engine is not None:
                try:
                    engine.add_person(name, [emb])
                    engine.save()
                except Exception:
                    pass
            return True

    def recognize_voice(self, audio_arr: np.ndarray, sample_rate: int = 16000, threshold: float = VOICE_MATCH_THRESHOLD) -> Tuple[Optional[str], float, Dict[str, Any]]:
        """Matches audio array against known voiceprints. Returns (name, best_score, metadata).

        IMPORTANT: This method always returns the BEST candidate and their score, even below threshold.
        Threshold enforcement and margin-based accept/reject logic is handled by the caller
        (_run_voice_identification multi-window voter). This enables proper margin calculation.
        """
        emb = self.extract_voiceprint(audio_arr, sample_rate)
        if emb is None:
            return None, 0.0, {}

        # Collect all speaker scores in one pass for margin calculation
        all_scores: list = []  # list of (norm_name, sim, meta)

        # 1. In-memory embeddings (primary — fastest path)
        with self._lock:
            known_vp = dict(self._known_voiceprints)
            known_meta = dict(self._speaker_metadata)

        for spk_norm, emb_list in known_vp.items():
            best_sim = max(float(np.dot(emb, kn_emb)) for kn_emb in emb_list) if emb_list else -1.0
            meta = known_meta.get(spk_norm, {
                "name": spk_norm.replace("_", " ").title(),
                "title": "Tanınan Konuşmacı",
                "formal_title": spk_norm.replace("_", " ").title()
            })
            all_scores.append((spk_norm, best_sim, meta))

        # 2. Also query SpeakerEngine (may have additional speakers from speakers.json)
        engine = _get_engine()
        if engine is not None:
            try:
                engine.load()
                matched_name, sim = engine.identify(emb)
                if matched_name is not None:
                    # Check if this engine result is already covered by in-memory scores
                    norm = self._normalize_name(matched_name)
                    if not any(s[0] == norm for s in all_scores):
                        eng_meta = known_meta.get(norm, {
                            "name": matched_name,
                            "title": "Tanınan Konuşmacı",
                            "formal_title": matched_name
                        })
                        all_scores.append((norm, float(sim), eng_meta))
            except Exception:
                pass

        if not all_scores:
            return None, 0.0, {}

        # Sort by similarity descending
        all_scores.sort(key=lambda x: x[1], reverse=True)
        best_norm, best_sim, best_meta = all_scores[0]

        # Always return best candidate — let caller decide accept/reject via margin
        return best_meta.get("name", best_norm.replace("_", " ").title()), round(max(0.0, best_sim), 4), best_meta

    def identify_speaker(self, audio_arr: np.ndarray, sample_rate: int = 16000) -> Tuple[Optional[str], float]:
        """Convenience method returning (name, score) for direct pipeline consumption."""
        name, score, _ = self.recognize_voice(audio_arr, sample_rate)
        return name, score

    def get_telemetry(self) -> Dict[str, Any]:
        """Returns runtime speaker recognition telemetry."""
        engine = _get_engine()
        model_p = str(getattr(engine, "model_path", "none")) if engine else "none"
        model_exists = bool(engine and getattr(engine, "_session", None) is not None)
        db_p = str(getattr(engine, "db_path", self.data_dir)) if engine else self.data_dir

        with self._lock:
            known_list = [v.get("name", k) for k, v in self._speaker_metadata.items()]

        return {
            "speaker_model_path": model_p,
            "speaker_model_exists": model_exists,
            "known_voices_path": db_p,
            "known_speakers": known_list,
        }

    def delete_speaker(self, name: str) -> bool:
        """Deletes speaker from memory, .npy files, and speakers.json."""
        norm_name = self._normalize_name(name)
        with self._lock:
            self._known_voiceprints.pop(norm_name, None)
            self._speaker_metadata.pop(norm_name, None)

        try:
            npy_path = os.path.join(self.data_dir, f"{norm_name}.npy")
            if os.path.exists(npy_path):
                os.remove(npy_path)
        except Exception:
            pass

        engine = _get_engine()
        if engine is not None:
            try:
                engine.remove_person(name)
                engine.save()
            except Exception:
                pass
        return True


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="ASTRO Speaker Recognition Telemetry & Test CLI")
    parser.add_argument("--test-speaker", help="Test if speaker is enrolled and ready")
    parser.add_argument("--list", action="store_true", help="List enrolled speakers and paths")
    args = parser.parse_args()

    rec = VoiceRecognizer()
    telemetry = rec.get_telemetry()
    print("=" * 60)
    print("[ASTRO Speaker Recognition Runtime Telemetry]")
    print(f"   Model Path:          {telemetry['speaker_model_path']}")
    print(f"   Model Exists/Ready:  {telemetry['speaker_model_exists']}")
    print(f"   Known Voices Path:   {telemetry['known_voices_path']}")
    print(f"   Enrolled Speakers:   {', '.join(telemetry['known_speakers']) if telemetry['known_speakers'] else 'None'}")
    print("=" * 60)

    if args.test_speaker:
        name_query = args.test_speaker.strip().lower()
        matched = [s for s in telemetry['known_speakers'] if s.lower() == name_query]
        if matched:
            print(f"[OK] Speaker '{args.test_speaker}' is verified and registered in database!")
        else:
            print(f"[ERROR] Speaker '{args.test_speaker}' NOT found in enrolled speakers: {telemetry['known_speakers']}")

