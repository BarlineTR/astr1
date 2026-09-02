#!/usr/bin/env python3
"""ASTRO V1 — Yüz algılama, tanıma ve kişi veritabanı.

OpenCV'nin kendi modelleriyle çalışır: YuNet (algılama) + SFace (128 boyutlu yüz
vektörü). Her ikisi de opencv-python içinde gelen API'lerdir — dlib/insightface
gibi ek bir bağımlılık, derleme ya da GPU gerektirmez. Yalnızca iki ONNX dosyası
indirilir (bkz. scripts/install_face_models.sh).

Hem ROS düğümü (face_detector_node) hem de kayıt betiği (scripts/enroll_face.py)
bu modülü kullanır; böylece kayıt ile tanıma tıpatıp aynı hizalama ve vektör
çıkarma yolunu izler.
"""
import json
import os
from pathlib import Path

import cv2
import numpy as np

DEFAULT_MODEL_DIR = Path(os.path.expanduser(os.getenv("FACE_MODEL_DIR", "~/.astro/models")))
DEFAULT_DB_PATH = Path(os.path.expanduser(os.getenv("FACE_DB_PATH", "~/.astro/faces/faces.json")))

YUNET_FILE = "yunet.onnx"
SFACE_FILE = "sface.onnx"

# OpenCV'nin SFace için belgelediği eşik 0.363'tür. Ancak known_faces galerisinde
# kişi başına tek fotoğraf olduğu için ölçtük: farklı kişilerin en yüksek benzerliği
# 0.414 (ali_yerlikaya ↔ hakan_fidan). 0.45, o yanlış eşleşmenin üstünde kalır.
# Asıl çözüm kişi başına 2-3 fotoğraf eklemektir; sonra 0.40'a indirilebilir.
DEFAULT_COSINE_THRESHOLD = float(os.getenv("FACE_MATCH_THRESHOLD", "0.45"))

# YuNet optimal input size for embedded Jetson CPU: 480 px (runs in < 4ms at 30 FPS)
MAX_DETECT_SIDE = 480


class FaceEngineUnavailable(RuntimeError):
    """Model dosyaları yok ya da yüklenemedi."""


class FaceEngine:
    """YuNet + SFace sarmalayıcısı ve tanınan kişiler veritabanı."""

    def __init__(
        self,
        model_dir=None,
        db_path=None,
        detect_threshold: float = 0.8,
        cosine_threshold: float = DEFAULT_COSINE_THRESHOLD,
    ):
        self.model_dir = Path(os.path.expanduser(str(model_dir))) if model_dir else DEFAULT_MODEL_DIR
        self.db_path = Path(os.path.expanduser(str(db_path))) if db_path else DEFAULT_DB_PATH
        self.cosine_threshold = cosine_threshold

        yunet = self.model_dir / YUNET_FILE
        sface = self.model_dir / SFACE_FILE
        missing = [str(p) for p in (yunet, sface) if not p.exists()]
        if missing:
            raise FaceEngineUnavailable(
                f"Yüz modelleri eksik: {', '.join(missing)} — ./scripts/install_face_models.sh çalıştırın"
            )

        try:
            self._detector = cv2.FaceDetectorYN.create(
                str(yunet), "", (320, 320), detect_threshold, 0.3, 5000
            )
            self._recognizer = cv2.FaceRecognizerSF.create(str(sface), "")
        except cv2.error as exc:
            raise FaceEngineUnavailable(f"Modeller yüklenemedi: {exc}") from exc

        self.people: dict[str, list[np.ndarray]] = {}
        self.load()

    # ------------------------------------------------------------------ algılama
    def detect(self, frame) -> np.ndarray:
        """Karedeki yüzleri döndürür (Nx15: kutu, 5 nokta, skor).

        Çok büyük görsellerde (örn. 3000 px'lik portreler) YuNet yüzü hiç
        bulamıyor; galeri fotoğraflarının 9/25'i bu yüzden kaçıyordu. Algılama
        küçültülmüş kopyada yapılıp koordinatlar orijinale geri ölçeklenir —
        hizalama (alignCrop) yine tam çözünürlüklü kareden yapılır.
        """
        height, width = frame.shape[:2]
        scale = min(1.0, MAX_DETECT_SIDE / max(height, width))

        if scale < 1.0:
            small = cv2.resize(frame, (int(width * scale), int(height * scale)))
            self._detector.setInputSize((small.shape[1], small.shape[0]))
            _retval, faces = self._detector.detect(small)
            if faces is None:
                return np.empty((0, 15), dtype=np.float32)
            faces = faces.copy()
            faces[:, :14] /= scale       # ilk 14 sütun koordinat, 15. skor
            return faces

        self._detector.setInputSize((width, height))
        _retval, faces = self._detector.detect(frame)
        return faces if faces is not None else np.empty((0, 15), dtype=np.float32)

    def embed(self, frame, face_row) -> np.ndarray:
        """Bir yüzü hizalayıp 128 boyutlu vektörünü çıkarır."""
        aligned = self._recognizer.alignCrop(frame, face_row)
        return self._recognizer.feature(aligned)

    def feature(self, aligned_face) -> np.ndarray:
        """Zaten 112x112'ye hizalanmış bir yüzden vektör çıkarır (hizalama yapmaz)."""
        return self._recognizer.feature(aligned_face)

    def embed_largest(self, frame):
        """Karedeki en büyük yüzün vektörünü döndürür; yüz yoksa None."""
        faces = self.detect(frame)
        if len(faces) == 0:
            return None
        largest = max(faces, key=lambda f: float(f[2]) * float(f[3]))
        return self.embed(frame, largest)

    # ------------------------------------------------------------------ tanıma
    def similarity(self, a, b) -> float:
        return float(self._recognizer.match(a, b, cv2.FaceRecognizerSF_FR_COSINE))

    def identify(self, feature) -> tuple[str | None, float]:
        """En yakın kişiyi bulur. Eşiğin altındaysa (None, skor) döner."""
        best_name, best_score = None, -1.0
        for name, vectors in self.people.items():
            for vector in vectors:
                score = self.similarity(feature, vector)
                if score > best_score:
                    best_name, best_score = name, score
        if best_score < self.cosine_threshold:
            return None, max(best_score, 0.0)
        return best_name, best_score

    # ------------------------------------------------------------------ veritabanı
    def load(self):
        self.people = {}
        if not self.db_path.exists():
            return
        try:
            data = json.loads(self.db_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return
        for name, vectors in data.get("people", {}).items():
            self.people[name] = [np.array(v, dtype=np.float32).reshape(1, -1) for v in vectors]

    def save(self):
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "people": {
                name: [v.flatten().tolist() for v in vectors]
                for name, vectors in self.people.items()
            },
        }
        self.db_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    def add_person(self, name: str, features: list[np.ndarray], replace: bool = False):
        if replace or name not in self.people:
            self.people[name] = []
        self.people[name].extend(features)

    def remove_person(self, name: str) -> bool:
        return self.people.pop(name, None) is not None

    def summary(self) -> str:
        if not self.people:
            return "kayıtlı kişi yok"
        return ", ".join(f"{n} ({len(v)} kare)" for n, v in sorted(self.people.items()))
