#!/usr/bin/env python3
"""ASTRO V1 — Sesten kişi tanıma (speaker recognition).

Konuşanın kim olduğunu sesinden ayırt eder. WeSpeaker ResNet34 (VoxCeleb) modeli
ONNX olarak çalıştırılır; onnxruntime zaten faster-whisper ile birlikte kurulu
olduğu için **yeni bir bağımlılık gerekmez** — yüz tanımadaki yaklaşımın aynısı.

Model 80 boyutlu Kaldi fbank özniteliği bekler. torchaudio bu ortamda yok
(numpy 2.x ile çakışır), bu yüzden fbank burada numpy ile Kaldi'nin tanımına
birebir uyacak şekilde hesaplanır: DC giderme → ön vurgu → Povey penceresi →
güç spektrumu → mel süzgeç bankası → log → zaman ekseninde ortalama çıkarma.

Kayıt ve tanıma aynı yolu kullanır (bkz. scripts/enroll_speaker.py).
"""
import json
import os
from pathlib import Path

import numpy as np

DEFAULT_MODEL_DIR = Path(os.path.expanduser(os.getenv("SPEAKER_MODEL_DIR", "~/.astro/models")))
DEFAULT_DB_PATH = Path(os.path.expanduser(os.getenv("SPEAKER_DB_PATH", "~/.astro/voices/speakers.json")))
MODEL_FILE = "speaker_resnet34.onnx"

# Ölçüm: aynı kişinin farklı parçaları 0.46-0.81, farklı kişiler 0.12-0.26 aralığında
# çıkıyor. 0.40 bu iki kümenin arasına düşer. Yükseltmek yanlış tanımayı azaltır ama
# "tanımadım" demesini sıklaştırır; gürültülü ortamda 0.45-0.50 deneyin.
DEFAULT_THRESHOLD = float(os.getenv("SPEAKER_MATCH_THRESHOLD", "0.40"))

SAMPLE_RATE = 16000
FRAME_LENGTH_MS = 25.0
FRAME_SHIFT_MS = 10.0
NUM_MEL_BINS = 80
PREEMPH = 0.97
LOW_FREQ = 20.0
EPS = float(np.finfo(np.float32).eps)

# Kısa parçalar güvenilir vektör vermez; robotun tek kelimelik seslerde
# yanlış kişiye atlamasını engeller.
MIN_SECONDS = 0.6


class SpeakerEngineUnavailable(RuntimeError):
    """Model dosyası yok ya da yüklenemedi."""


def to_16k_mono(audio: np.ndarray, sample_rate: int, channels: int = 1) -> np.ndarray:
    """Herhangi bir kaydı modelin beklediği 16 kHz tek kanala çevirir.

    Doğrusal aradeğerleme (np.interp) ile indirmek örtüşme (aliasing) yaratıp aynı
    kişinin benzerlik skorunu belirgin biçimde düşürüyordu; scipy'nin çok fazlı
    yeniden örneklemesi alçak geçiren süzgeci de uygular.
    """
    if channels > 1:
        audio = audio.reshape(-1, channels)[:, 0]
    audio = np.asarray(audio, dtype=np.float32)
    if sample_rate == SAMPLE_RATE:
        return audio

    try:
        from math import gcd

        from scipy.signal import resample_poly

        divisor = gcd(int(sample_rate), SAMPLE_RATE)
        return resample_poly(audio, SAMPLE_RATE // divisor, int(sample_rate) // divisor).astype(np.float32)
    except ImportError:
        indices = np.linspace(0, audio.size - 1, int(audio.size * SAMPLE_RATE / sample_rate))
        return np.interp(indices, np.arange(audio.size), audio).astype(np.float32)


def _mel_scale(freq):
    return 1127.0 * np.log(1.0 + freq / 700.0)


def _mel_filterbank(num_bins: int, fft_size: int, sample_rate: int) -> np.ndarray:
    """Kaldi'nin üçgen mel süzgeç bankası (compute-fbank-feats ile aynı tanım)."""
    num_fft_bins = fft_size // 2
    nyquist = 0.5 * sample_rate
    fft_bin_width = sample_rate / fft_size

    mel_low, mel_high = _mel_scale(LOW_FREQ), _mel_scale(nyquist)
    mel_delta = (mel_high - mel_low) / (num_bins + 1)

    bank = np.zeros((num_bins, num_fft_bins + 1), dtype=np.float32)
    for b in range(num_bins):
        left, center, right = (mel_low + mel_delta * (b + offset) for offset in (0, 1, 2))
        for i in range(num_fft_bins):
            mel = _mel_scale(fft_bin_width * i)
            if left < mel < right:
                bank[b, i] = (
                    (mel - left) / (center - left) if mel <= center
                    else (right - mel) / (right - center)
                )
    return bank


def compute_fbank(waveform: np.ndarray, sample_rate: int = SAMPLE_RATE) -> np.ndarray:
    """int16 ölçekli dalga formundan (T, 80) log-mel öznitelik üretir."""
    wave = waveform.astype(np.float32)
    # Kaldi pencere boyutlarını ms cinsinden tanımlar; örnekleme hızı değişince
    # örnek sayısı da değişmeli (16 kHz'de 400/160, 24 kHz'de 600/240).
    frame_length = int(sample_rate * FRAME_LENGTH_MS / 1000.0)
    frame_shift = int(sample_rate * FRAME_SHIFT_MS / 1000.0)
    if wave.size < frame_length:
        raise ValueError("ses çok kısa")

    num_frames = 1 + (wave.size - frame_length) // frame_shift
    indices = np.arange(frame_length)[None, :] + frame_shift * np.arange(num_frames)[:, None]
    frames = wave[indices]

    frames = frames - frames.mean(axis=1, keepdims=True)          # DC giderme
    shifted = np.concatenate([frames[:, :1], frames[:, :-1]], axis=1)
    frames = frames - PREEMPH * shifted                            # ön vurgu

    n = np.arange(frame_length)
    povey = (0.5 - 0.5 * np.cos(2 * np.pi * n / (frame_length - 1))) ** 0.85
    frames = frames * povey.astype(np.float32)

    fft_size = 1
    while fft_size < frame_length:
        fft_size *= 2
    spectrum = np.fft.rfft(frames, n=fft_size)
    power = (spectrum.real ** 2 + spectrum.imag ** 2).astype(np.float32)

    bank = _mel_filterbank(NUM_MEL_BINS, fft_size, sample_rate)
    energies = power @ bank.T
    feats = np.log(np.maximum(energies, EPS))

    # Kanal/mikrofon farkını bastıran ortalama çıkarma (CMN)
    return (feats - feats.mean(axis=0, keepdims=True)).astype(np.float32)


class SpeakerEngine:
    """WeSpeaker ONNX sarmalayıcısı ve kayıtlı konuşmacı veritabanı."""

    def __init__(self, model_dir=None, db_path=None, threshold: float = DEFAULT_THRESHOLD):
        self.model_dir = Path(os.path.expanduser(str(model_dir))) if model_dir else DEFAULT_MODEL_DIR
        self.db_path = Path(os.path.expanduser(str(db_path))) if db_path else DEFAULT_DB_PATH
        self.threshold = threshold

        model_path = self.model_dir / MODEL_FILE
        if not model_path.exists():
            raise SpeakerEngineUnavailable(
                f"Konuşmacı modeli yok: {model_path} — ./scripts/install_face_models.sh çalıştırın"
            )
        try:
            import onnxruntime as ort
        except ImportError as exc:
            raise SpeakerEngineUnavailable("onnxruntime kurulu değil") from exc

        options = ort.SessionOptions()
        options.intra_op_num_threads = 1          # robotta CPU'yu tek çekirdekte tut
        try:
            self._session = ort.InferenceSession(
                str(model_path), sess_options=options, providers=["CPUExecutionProvider"]
            )
        except Exception as exc:
            raise SpeakerEngineUnavailable(f"Model yüklenemedi: {exc}") from exc

        self.people: dict[str, list[np.ndarray]] = {}
        self.load()

    # ------------------------------------------------------------------ vektör
    def embed(self, audio_int16: np.ndarray, sample_rate: int = SAMPLE_RATE) -> np.ndarray | None:
        """int16 ses dizisinden 256 boyutlu, birim uzunluklu konuşmacı vektörü."""
        if audio_int16.size < MIN_SECONDS * sample_rate:
            return None
        feats = compute_fbank(np.asarray(audio_int16, dtype=np.float32), sample_rate)
        embedding = self._session.run(None, {"feats": feats[None, :, :]})[0][0]
        norm = np.linalg.norm(embedding)
        return (embedding / norm).astype(np.float32) if norm > 0 else None

    @staticmethod
    def similarity(a: np.ndarray, b: np.ndarray) -> float:
        """Birim vektörlerde kosinüs benzerliği = iç çarpım."""
        return float(np.dot(a, b))

    def identify(self, embedding: np.ndarray) -> tuple[str | None, float]:
        best_name, best_score = None, -1.0
        for name, vectors in self.people.items():
            for vector in vectors:
                score = self.similarity(embedding, vector)
                if score > best_score:
                    best_name, best_score = name, score
        if best_score < self.threshold:
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
            self.people[name] = [np.array(v, dtype=np.float32) for v in vectors]

    def save(self):
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "people": {n: [v.tolist() for v in vs] for n, vs in self.people.items()},
        }
        self.db_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    def add_person(self, name: str, embeddings: list[np.ndarray], replace: bool = False):
        if replace or name not in self.people:
            self.people[name] = []
        self.people[name].extend(embeddings)

    def remove_person(self, name: str) -> bool:
        return self.people.pop(name, None) is not None

    def summary(self) -> str:
        if not self.people:
            return "kayıtlı kişi yok"
        return ", ".join(f"{n} ({len(v)} kayıt)" for n, v in sorted(self.people.items()))
