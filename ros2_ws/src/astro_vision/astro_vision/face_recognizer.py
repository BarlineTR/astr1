#!/usr/bin/env python3
"""ASTRO V1 — Face Recognition & Biometric Identity Engine.

Features:
  - Canonical Face Alignment & 112x112 Spatial Feature Vectorization
  - Cosine Distance Metric for Instant Profile Identification
  - Auto-discovery of known faces in data/known_faces/ directory
  - Pre-seeded profiles for Bitlis & Turkey Government Officials
  - Dynamic On-The-Fly Enrollment (learn new faces in real time)
"""

import json
import logging

_LOG = logging.getLogger(__name__)

import os
import re
import threading
import numpy as np
try:
    import cv2
except ImportError:
    cv2 = None
from typing import Any, Dict, List, Optional, Tuple


try:
    from astro_vision.face_db import FaceEngine, FaceEngineUnavailable
except ImportError:  # paket kaynaktan çalıştırılıyorsa
    try:
        from face_db import FaceEngine, FaceEngineUnavailable
    except ImportError:
        FaceEngine = None

        class FaceEngineUnavailable(RuntimeError):
            pass

# OpenCV SFace için belgelenen eşik: kosinüs >= 0.363 aynı kişi (mobil ekran / ışık toleransı için 0.38 idealdir).
FACE_MATCH_THRESHOLD = float(os.getenv("FACE_MATCH_THRESHOLD", "0.38"))

_ENGINE = None
_ENGINE_TRIED = False


def _get_engine():
    """SFace motorunu bir kez yükler (model ~37 MB); yoksa None döner."""
    global _ENGINE, _ENGINE_TRIED
    if not _ENGINE_TRIED:
        _ENGINE_TRIED = True
        if FaceEngine is not None:
            try:
                _ENGINE = FaceEngine()
            except FaceEngineUnavailable as exc:
                print(f"[FaceRecognizer] Yüz modelleri yüklenemedi: {exc}")
    return _ENGINE


class FaceRecognizer:
    """Manages facial feature embeddings, known gallery indexing, and matching."""
    EMBEDDING_DIM: int = 128  # OpenCV SFace standard embedding dimension

    def __init__(self, data_dir: Optional[str] = None, threshold: float = FACE_MATCH_THRESHOLD):
        from pathlib import Path
        self.threshold = threshold
        if data_dir is None:
            # Check environment, ament package share, source tree, and standard robot paths
            candidates = []
            env_dir = os.getenv("ASTRO_KNOWN_FACES_DIR")
            if env_dir:
                candidates.append(os.path.abspath(env_dir))

            try:
                from ament_index_python.packages import get_package_share_directory
                share_dir = get_package_share_directory("astro_vision")
                candidates.append(os.path.join(share_dir, "data", "known_faces"))
            except Exception:
                pass

            this_p = Path(__file__).resolve()
            candidates.append(str(this_p.parent.parent / "data" / "known_faces"))
            candidates.append(str(this_p.parent / "data" / "known_faces"))

            # Install space climbing back to source tree
            try:
                candidates.append(str(this_p.parents[3] / "src" / "astro_vision" / "data" / "known_faces"))
                candidates.append(str(this_p.parents[4] / "src" / "astro_vision" / "data" / "known_faces"))
                candidates.append(str(this_p.parents[5] / "ros2_ws" / "src" / "astro_vision" / "data" / "known_faces"))
            except IndexError:
                pass

            # Standard robot and workspace paths
            candidates.append(str(Path.home() / "Desktop" / "astr1" / "ros2_ws" / "src" / "astro_vision" / "data" / "known_faces"))
            candidates.append(str(Path.home() / ".astro" / "known_faces"))
            candidates.append(os.path.abspath("./ros2_ws/src/astro_vision/data/known_faces"))
            candidates.append(os.path.abspath("./data/known_faces"))

            self.data_dir = None
            for c in candidates:
                if c and os.path.exists(c) and len(os.listdir(c)) > 0:
                    self.data_dir = os.path.abspath(c)
                    break
            if self.data_dir is None:
                self.data_dir = os.path.abspath(candidates[0] if candidates else "./data/known_faces")
        else:
            self.data_dir = os.path.abspath(data_dir)

        os.makedirs(self.data_dir, exist_ok=True)
        self._lock = threading.RLock()
        self._known_embeddings: Dict[str, List[np.ndarray]] = {}
        self._person_metadata: Dict[str, Dict[str, Any]] = {}

        # Pre-seed default government & creator profiles
        self._init_default_profiles()
        # Scan and index existing images on disk
        self.reload_gallery()

    def _init_default_profiles(self):
        """Initializes metadata templates for Bitlis & Turkey officials and cabinet members."""
        defaults = {
            # Protokol ve Yaratıcı
            "Recep Tayyip Erdoğan": {"title": "Cumhurbaşkanı", "formal_title": "Sayın Cumhurbaşkanım", "category": "head_of_state"},
            "Cevdet Yılmaz": {"title": "Cumhurbaşkanı Yardımcısı", "formal_title": "Sayın Cumhurbaşkanı Yardımcım", "category": "executive"},
            "Baran": {"title": "Baş Mühendis & Yaratıcı", "formal_title": "Baran Bey", "category": "creator"},
            "Selçuk Bayraktar": {"title": "Baykar Yönetim Kurulu Başkanı", "formal_title": "Sayın Bayraktar", "category": "industry"},
            # Kabine Üyeleri
            "Hakan Fidan": {"title": "Dışişleri Bakanı", "formal_title": "Sayın Bakanım", "category": "minister"},
            "Ali Yerlikaya": {"title": "İçişleri Bakanı", "formal_title": "Sayın Bakanım", "category": "minister"},
            "Mehmet Şimşek": {"title": "Hazine ve Maliye Bakanı", "formal_title": "Sayın Bakanım", "category": "minister"},
            "Yaşar Güler": {"title": "Milli Savunma Bakanı", "formal_title": "Sayın Bakanım", "category": "minister"},
            "Yılmaz Tunç": {"title": "Adalet Bakanı", "formal_title": "Sayın Bakanım", "category": "minister"},
            "Mehmet Fatih Kacır": {"title": "Sanayi ve Teknoloji Bakanı", "formal_title": "Sayın Bakanım", "category": "minister"},
            "Alparslan Bayraktar": {"title": "Enerji ve Tabii Kaynaklar Bakanı", "formal_title": "Sayın Bakanım", "category": "minister"},
            "Murat Kurum": {"title": "Çevre, Şehircilik ve İklim Değişikliği Bakanı", "formal_title": "Sayın Bakanım", "category": "minister"},
            "Yusuf Tekin": {"title": "Milli Eğitim Bakanı", "formal_title": "Sayın Bakanım", "category": "minister"},
            "Abdulkadir Uraloğlu": {"title": "Ulaştırma ve Altyapı Bakanı", "formal_title": "Sayın Bakanım", "category": "minister"},
            "İbrahim Yumaklı": {"title": "Tarım ve Orman Bakanı", "formal_title": "Sayın Bakanım", "category": "minister"},
            "Kemal Memişoğlu": {"title": "Sağlık Bakanı", "formal_title": "Sayın Bakanım", "category": "minister"},
            "Mahinur Özdemir Göktaş": {"title": "Aile ve Sosyal Hizmetler Bakanı", "formal_title": "Sayın Bakanım", "category": "minister"},
            "Ömer Bolat": {"title": "Ticaret Bakanı", "formal_title": "Sayın Bakanım", "category": "minister"},
            "Osman Aşkın Bak": {"title": "Gençlik ve Spor Bakanı", "formal_title": "Sayın Bakanım", "category": "minister"},
            "Vedat Işıkhan": {"title": "Çalışma ve Sosyal Güvenlik Bakanı", "formal_title": "Sayın Bakanım", "category": "minister"},
            "Mehmet Nuri Ersoy": {"title": "Kültür ve Turizm Bakanı", "formal_title": "Sayın Bakanım", "category": "minister"},
            # Bitlis ve Bölge Mülki İdare
            "Erol Karaömeroğlu": {"title": "Bitlis Eski Valisi", "formal_title": "Sayın Valim", "category": "governor"},
            "Ahmet Karakaya": {"title": "Bitlis Valisi", "formal_title": "Sayın Valim", "category": "governor"},
            "Nesrullah Tanğlay": {"title": "Bitlis Belediye Başkanı", "formal_title": "Sayın Başkanım", "category": "mayor"},
            "Batuhan Bingöl": {"title": "Ahlat Kaymakamı", "formal_title": "Sayın Kaymakamım", "category": "district_governor"},
            "Yavuz Gülmez": {"title": "Ahlat Belediye Başkanı", "formal_title": "Sayın Başkanım", "category": "mayor"},
        }
        for name, meta in defaults.items():
            norm = self._normalize_name(name)
            self._person_metadata[norm] = {"name": name, **meta}

    def _normalize_name(self, name: str) -> str:
        """Converts name to standard identifier (e.g. 'Erol Karaömeroğlu' -> 'erol_karaomeroglu')."""
        tr_map = str.maketrans("çğıöşüÇĞİÖŞÜ", "cgiosuCGIOSU")
        clean = name.translate(tr_map).lower()
        clean = re.sub(r"[^a-z0-9_]+", "_", clean).strip("_")
        return clean or "unknown"

    def extract_embedding(self, face_bgr: np.ndarray) -> Optional[np.ndarray]:
        """Yüz kırpıntısından L2-normalize edilmiş SFace vektörü çıkarır.

        Eskiden histogram/HOG tabanlı elle yazılmış öznitelikler kullanılıyordu;
        bunlar ışık ve poz değişiminde kolayca karışıyordu. SFace derin gömmesiyle
        ölçülen ayrım: aynı kişi 0.74-0.95, farklı kişi 0.10-0.26.

        Kırpıntıda yüz yeniden bulunabilirse hizalama (alignCrop) yapılır — vektör
        kalitesini belirgin artırır; bulunamazsa 112x112'ye ölçeklenip doğrudan
        modele verilir.
        """
        if face_bgr is None or face_bgr.size == 0:
            return None

        engine = _get_engine()
        if engine is None or cv2 is None:
            return None

        try:
            faces = engine.detect(face_bgr)
            if len(faces) > 0:
                largest = max(faces, key=lambda f: float(f[2]) * float(f[3]))
                feature = engine.embed(face_bgr, largest)
            elif face_bgr.shape[0] < 350 and face_bgr.shape[1] < 350 and (0.6 < face_bgr.shape[1] / max(1, face_bgr.shape[0]) < 1.6):
                # Pre-cropped face ROI from an upstream detector where landmarks weren't found
                aligned = cv2.resize(face_bgr, (112, 112))
                feature = engine.feature(aligned)
            else:
                # Full scene / empty frame without a detected face -> strictly NOT A FACE
                return None
        except Exception:
            return None

        vector = np.asarray(feature, dtype=np.float32).flatten()
        norm = float(np.linalg.norm(vector))
        # Galeri karşılaştırması düz iç çarpım yapıyor; normalize etmezsek
        # iç çarpım kosinüs olmaz ve eşik anlamını yitirir.
        return vector / norm if norm > 1e-6 else None

    def reload_gallery(self):
        """Scans data_dir for person directories and indexes face images + ~/.astro/faces/faces.json."""
        engine = _get_engine()
        if engine is not None:
            try:
                engine.load()
            except Exception as _exc:
                _LOG.debug("reload_gallery: yok sayılan hata (%s)", _exc)

        with self._lock:
            self._known_embeddings.clear()
            # 1. Load from FaceEngine database if available
            if engine is not None and getattr(engine, "people", None):
                for person_name, vectors in engine.people.items():
                    norm = self._normalize_name(person_name)
                    self._known_embeddings.setdefault(norm, []).extend(vectors)
                    if norm not in self._person_metadata:
                        self._person_metadata[norm] = {
                            "name": person_name,
                            "title": "Tanınan Kişi",
                            "formal_title": person_name,
                            "category": "guest"
                        }

            # 2. Load from data_dir image files
            if os.path.exists(self.data_dir):
                indexed_count = 0
                for entry in sorted(os.listdir(self.data_dir)):
                    entry_path = os.path.join(self.data_dir, entry)
                    if os.path.isdir(entry_path):
                        person_norm = self._normalize_name(entry)
                        for f in sorted(os.listdir(entry_path)):
                            if f.lower().endswith((".jpg", ".jpeg", ".png", ".bmp")):
                                img_p = os.path.join(entry_path, f)
                                if cv2 is not None:
                                    img = cv2.imread(img_p)
                                    if img is not None:
                                        emb = self.extract_embedding(img)
                                        if emb is not None:
                                            self._known_embeddings.setdefault(person_norm, []).append(emb)
                                            indexed_count += 1
                    elif entry.lower().endswith((".jpg", ".jpeg", ".png")):
                        person_name = os.path.splitext(entry)[0]
                        person_norm = self._normalize_name(person_name)
                        if cv2 is not None:
                            img = cv2.imread(entry_path)
                            if img is not None:
                                emb = self.extract_embedding(img)
                                if emb is not None:
                                    self._known_embeddings.setdefault(person_norm, []).append(emb)
                                    indexed_count += 1

            total_embs = sum(len(v) for v in self._known_embeddings.values())
            _LOG.info("👤 [FaceRecognizer] Galeri hazır: %d kişi, %d şablon yüklendi (data_dir=%s)", len(self._known_embeddings), total_embs, self.data_dir)

    def enroll_face(self, name: str, face_bgr: np.ndarray, title: Optional[str] = None) -> bool:
        """Dynamically learns and saves a new face to disk and memory."""
        if face_bgr is None or not name:
            return False

        emb = self.extract_embedding(face_bgr)
        if emb is None:
            return False

        norm_name = self._normalize_name(name)
        with self._lock:
            # Add to in-memory embeddings
            self._known_embeddings.setdefault(norm_name, []).append(emb)
            if norm_name not in self._person_metadata:
                self._person_metadata[norm_name] = {
                    "name": name,
                    "title": title or "Misafir",
                    "formal_title": title or name,
                    "category": "guest"
                }

            # Persist to disk
            try:
                person_dir = os.path.join(self.data_dir, norm_name)
                os.makedirs(person_dir, exist_ok=True)
                filename = f"face_{int(np.random.randint(1000, 9999))}.jpg"
                cv2.imwrite(os.path.join(person_dir, filename), face_bgr)
            except Exception as _exc:
                _LOG.debug("enroll_face: yok sayılan hata (%s)", _exc)

            # Save to FaceEngine database
            engine = _get_engine()
            if engine is not None:
                try:
                    engine.add_person(name, [emb])
                    engine.save()
                except Exception as _exc:
                    _LOG.debug("enroll_face: yok sayılan hata (%s)", _exc)
            return True

    def recognize_face(self, face_bgr: np.ndarray, threshold: Optional[float] = None) -> Tuple[Optional[str], float, Dict[str, Any]]:
        """Matches a face ROI against the known gallery. Returns (name, confidence, metadata)."""
        eff_thresh = float(threshold if threshold is not None else self.threshold)
        emb = self.extract_embedding(face_bgr)
        if emb is None:
            return None, 0.0, {}

        # 1. First try FaceEngine directly if it has registered people
        engine = _get_engine()
        if engine is not None and getattr(engine, "people", None):
            try:
                matched_name, sim = engine.identify(emb)
                if matched_name is not None and sim >= eff_thresh:
                    norm = self._normalize_name(matched_name)
                    meta = self._person_metadata.get(norm, {
                        "name": matched_name,
                        "title": "Tanınan Kişi",
                        "formal_title": matched_name
                    })
                    return meta["name"], round(float(sim), 2), meta
            except Exception as _exc:
                _LOG.debug("recognize_face: yok sayılan hata (%s)", _exc)

        # 2. Fallback to in-memory matching against known_faces
        with self._lock:
            if not self._known_embeddings:
                return None, 0.0, {}

            best_match = None
            highest_sim = -1.0

            for person_norm, emb_list in self._known_embeddings.items():
                for known_emb in emb_list:
                    sim = float(np.dot(emb.flatten(), np.asarray(known_emb).flatten()))
                    if sim > highest_sim:
                        highest_sim = sim
                        best_match = person_norm

            if best_match is not None and highest_sim >= eff_thresh:
                meta = self._person_metadata.get(best_match, {
                    "name": best_match.replace("_", " ").title(),
                    "title": "Tanınan Kişi",
                    "formal_title": best_match.replace("_", " ").title()
                })
                return meta["name"], round(highest_sim, 2), meta

            cand_name = best_match.replace("_", " ").title() if best_match else "Bilinmeyen"
            return None, max(0.0, round(highest_sim, 2)), {"candidate": cand_name}

