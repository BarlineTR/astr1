#!/usr/bin/env python3
"""Sesli yanıt döngüsü — ROS'suz.

ROS'lu tarafta bu iş beş düğüme dağılmış ve aralarındaki her şey topic:
audio_stream_node → speech_recognition_node → ai_brain_node → tts_node, artı
yankı bastırma için geri dönen `/tts/speaking`. Buradaki dosya o topolojinin
yerine geçen kablolama; karar veren nesnelerin hepsi paylaşılan kütüphanelerden
geliyor (`STTRouter`, `TTSRouter`, `AudioOutputManager`, `ConversationSession`).
"""

import io
import wave
from typing import Any, Optional

import numpy as np

import core_path  # noqa: F401
from astro_ai.conversation_session import ConversationSession  # noqa: E402
from astro_audio.speech_detector import SpeechDetector  # noqa: E402

# Sözce sonu eşiği. Cümle içi duraklamayı sözce sonundan ayırmalı: hece arası
# ≤0.25 s, virgül duraklaması ~0.5 s, cümle sonu daha uzun. 0.8 s ikisinin
# arasında ve tur gecikmesini hissedilir kılmıyor. Gerçek kayıtla yeniden
# ayarlanacak, o yüzden dışarıdan verilebiliyor.
DEFAULT_SILENCE_S = 0.8

# Susmayan bir kaynak (açık televizyon, uğultu) tamponu sonsuza büyütmesin.
DEFAULT_MAX_UTTERANCE_S = 10.0

# STT'nin beklediği hız. Tampon yakalama hızında tutulur (dizi modunda 16 kHz,
# stereo modda aygıtın kendi hızı — laptopta 44.1 kHz) ve dönüşüm tek noktada,
# STT'ye verilmeden hemen önce yapılır. Hızın sessizce varsayılması bu depoda
# daha önce bedel ödetti: int16 eşiği float32 akışa uygulanmıştı ve kapı her
# bloğu eliyordu.
STT_SAMPLE_RATE = 16000

WAKE_WORD = "hey astro"

# Hoparlör sustuktan sonra mikrofonun kendi sesini duymayı bırakması zaman alır.
# .env'deki ECHO_MUTE_COOLDOWN_S ile aynı sayı; bayrak anında düşerse yolda olan
# kendi ses transkribe edilir ve robot kendine cevap verir.
DEFAULT_ECHO_COOLDOWN_S = 0.65

# Robot konuşurken araya girmeyi ciddiye almadan önce görülmesi gereken kesintisiz
# konuşma. Tek blok (64 ms) hoparlör sızıntısıyla da olabilir; 0.3 s bir hecedir.
DEFAULT_BARGE_IN_S = 0.3


class UtteranceTracker:
    """Blok blok gelen konuşma kararlarından sözce sınırı çıkarır.

    Kararın kendisini üretmez — o `astro_audio.speech_detector`'ın işi. Burada
    yalnızca "ne zaman başladı, ne zaman bitti" var, çünkü sözce sınırı bir
    zamanlama sorusu, akustik bir soru değil.
    """

    def __init__(
        self,
        sample_rate: int,
        silence_s: float = DEFAULT_SILENCE_S,
        max_s: float = DEFAULT_MAX_UTTERANCE_S,
    ):
        self.sample_rate = int(sample_rate)
        self.silence_s = float(silence_s)
        self.max_s = float(max_s)
        self._chunks: list = []
        self._silence_started_at: Optional[float] = None
        self._samples = 0

    @property
    def active(self) -> bool:
        return bool(self._chunks)

    def feed(self, is_speech: bool, block: np.ndarray, timestamp: float) -> Optional[np.ndarray]:
        """Bir bloğu işler. Sözce bu çevrimde kapandıysa tamamını döndürür."""
        samples = np.asarray(block, dtype=np.float32).ravel()

        if is_speech:
            self._chunks.append(samples)
            self._samples += len(samples)
            self._silence_started_at = None
        elif self._chunks:
            # Sözce açıkken gelen sessizlik saklanır — cümle içi duraklama sözcenin
            # parçasıdır ve atılırsa kelimeler birbirine yapışır.
            self._chunks.append(samples)
            self._samples += len(samples)

            if self._silence_started_at is None:
                self._silence_started_at = timestamp
            elif (timestamp - self._silence_started_at) >= self.silence_s:
                return self._close()
        else:
            # Sözce başlamadı: sessizlik biriktirilmez.
            return None

        # Azami süre sınırı, konuşma veya sessizlik bloğu eklendikten sonra uygulanır.
        if self._samples >= int(self.max_s * self.sample_rate):
            return self._close()
        return None

    def _close(self) -> np.ndarray:
        utterance = np.concatenate(self._chunks) if self._chunks else np.zeros(0, np.float32)
        self._chunks = []
        self._samples = 0
        self._silence_started_at = None
        return utterance


def resample_to(mono: np.ndarray, from_rate: int, to_rate: int) -> np.ndarray:
    """Doğrusal ara değerle yeniden örnekler.

    Konuşma tanıma için yeterli: STT modelleri kendi ön işlemesinde zaten
    bant sınırlıyor, ve buradaki tek amaç hızı sözleşmeye getirmek.
    """
    if from_rate == to_rate or len(mono) == 0:
        return np.asarray(mono, dtype=np.float32)
    count = int(round(len(mono) * (to_rate / float(from_rate))))
    if count <= 0:
        return np.zeros(0, dtype=np.float32)
    source = np.linspace(0.0, len(mono) - 1, num=count)
    return np.interp(source, np.arange(len(mono)), mono).astype(np.float32)


def to_wav_bytes(mono: np.ndarray, sample_rate: int) -> bytes:
    """float32 [-1, 1] mono sesi 16-bit PCM WAV'a çevirir (STT'nin istediği)."""
    clipped = np.clip(np.asarray(mono, dtype=np.float32), -1.0, 1.0)
    pcm16 = (clipped * 32767.0).astype(np.int16)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(int(sample_rate))
        handle.writeframes(pcm16.tobytes())
    return buffer.getvalue()


class VoiceLoop:
    """Bir konuşma turunu baştan sona yürütür.

    Bütün sağlayıcılar enjekte edilebilir: testler sahtelerle koşar ve ağ
    çağrısı yapmaz, ve hangi sağlayıcının konuştuğu çağıranın kararı kalır.
    """

    def __init__(
        self,
        audio: Any = None,
        stt: Any = None,
        llm: Any = None,
        tts: Any = None,
        output: Any = None,
        session: Optional[ConversationSession] = None,
        speech: Optional[SpeechDetector] = None,
        wake_word: str = WAKE_WORD,
        silence_s: float = DEFAULT_SILENCE_S,
        echo_cooldown_s: float = DEFAULT_ECHO_COOLDOWN_S,
        barge_in_s: float = DEFAULT_BARGE_IN_S,
    ):
        self.audio = audio
        self.stt = stt
        self.llm = llm
        self.tts = tts
        self.output = output
        self.session = session or ConversationSession()
        self.speech = speech or SpeechDetector(sample_rate=STT_SAMPLE_RATE)
        self.wake_word = wake_word
        self.silence_s = float(silence_s)
        self.echo_cooldown_s = float(echo_cooldown_s)
        self.barge_in_s = float(barge_in_s)
        self._playing = False
        self._playback_ended_at: Optional[float] = None
        self._barge_in_since: Optional[float] = None
        # Sözce takipçisi **yakalama** hızıyla kurulur, STT hızıyla değil. Bloklar
        # tampondan yakalama hızında geliyor (dizi modunda 16 kHz, stereo modda
        # aygıtın kendi hızı — laptopta 44.1 kHz); STT hızını varsaymak sözce üst
        # sınırını 2.75 kat yanlış hesaplardı. Dönüşüm yalnızca STT'ye girerken.
        capture_rate = int(getattr(audio, "sample_rate", 0) or STT_SAMPLE_RATE)
        self._utterance = UtteranceTracker(sample_rate=capture_rate,
                                           silence_s=self.silence_s)

    @property
    def is_speaking(self) -> bool:
        """Anlık durum. Zamana bağlı karar için `is_speaking_at` kullanılır."""
        if self.output is not None and getattr(self.output, "is_playing", False):
            return True
        return self._playing

    def note_playback(self, is_playing: bool, timestamp: float) -> None:
        """`AudioOutputManager`'ın çalma durumu değişince çağrılır."""
        if not is_playing and self._playing:
            self._playback_ended_at = float(timestamp)
        self._playing = bool(is_playing)

    def is_speaking_at(self, timestamp: float) -> bool:
        """Robot şu anda konuşuyor mu — yankı soğuması dahil."""
        if self._playing:
            return True
        if self._playback_ended_at is None:
            return False
        return (timestamp - self._playback_ended_at) < self.echo_cooldown_s

    def on_block(self, is_speech: bool, block: np.ndarray,
                 timestamp: float) -> Optional[np.ndarray]:
        """Bir ses bloğunu işler. Sözce kapandıysa tamamını döndürür.

        Robot konuşurken sözce biriktirilmez — biriktirilse robotun kendi sesi
        transkribe edilirdi. Blok yine de okunur, çünkü araya girmeyi ancak
        dinleyerek fark edebiliriz.
        """
        if self.is_speaking_at(timestamp):
            self._check_barge_in(is_speech, timestamp)
            return None

        self._barge_in_since = None
        return self._utterance.feed(is_speech, block, timestamp)

    def _check_barge_in(self, is_speech: bool, timestamp: float) -> None:
        if not is_speech:
            self._barge_in_since = None
            return
        if self._barge_in_since is None:
            self._barge_in_since = timestamp
            return
        if (timestamp - self._barge_in_since) >= self.barge_in_s:
            if self.output is not None:
                self.output.interrupt()
            self._playing = False
            self._playback_ended_at = timestamp
            self._barge_in_since = None

    def handle_utterance(self, utterance: np.ndarray, sample_rate: int) -> Optional[str]:
        """Bir sözceyi tura çevirir. Söylenen cevabı, yoksa None döndürür."""
        if self.stt is None or utterance is None or len(utterance) == 0:
            return None

        audio = resample_to(utterance, sample_rate, STT_SAMPLE_RATE)
        result = self.stt.transcribe(audio, to_wav_bytes(audio, STT_SAMPLE_RATE),
                                     sample_rate=STT_SAMPLE_RATE)
        text = (getattr(result, "text", None) or "").strip()
        if not text:
            return None

        has_wake, clean = self.session.is_wake_word(text, self.wake_word)
        if has_wake:
            self.session.activate_session(reason="wake_word")
        elif not self.session.is_active():
            # Oturum kapalı ve çağrılmadık: bu konuşma bize değil.
            return None
        # else: yapacak bir şey yok — is_wake_word() uyandırma sözcüğü bulamasa
        # bile normalize edilmiş metni döndürür, devam turu zaten `clean`'de
        # ihtiyacı olanı buluyor.

        self.session.record_user_speech()
        prompt = clean.strip() or text
        answer = self.llm.reply(prompt) if self.llm is not None else None
        if not answer:
            return None

        self._speak(answer)
        return answer

    def _speak(self, text: str) -> None:
        if self.tts is None:
            return
        generation_id = self.output.new_generation() if self.output is not None else 0
        self.tts.synthesize_and_play(text, generation_id=generation_id,
                                     output_manager=self.output, language="tr")
        self.session.record_robot_speech()
