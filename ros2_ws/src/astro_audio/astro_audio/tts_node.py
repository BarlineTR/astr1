#!/usr/bin/env python3
"""ASTRO V1 — Text-to-Speech Node (Edge-TTS / XTTS + sounddevice playback).

Subscribes to:
  /tts/say       (String) — text to speak
  /tts/interrupt  (Bool)  — cancel current playback

Publishes:
  /tts/speaking  (Bool)   — True while audio is playing (echo prevention)

Features:
  - Streaming sentence playback queue
  - Two engines via TTS_ENGINE: "edge-tts" (cloud, default) and "xtts"
    (local Coqui XTTS v2 voice cloning, offline, GPU recommended)
  - Fallback audio players (sounddevice -> paplay -> aplay -> ffplay)
  - Interruption handling with generation counter

XTTS runs as a separate process in its own virtualenv (see xtts_client.py and
scripts/install_xtts.sh) — it cannot be installed into this interpreter, because
it needs numpy 1.26 while rclpy here is pinned to numpy 2.2.
"""

import os
import re
import asyncio
import tempfile
import subprocess
import threading
import queue
import numpy as np

import rclpy
from rclpy.node import Node
from std_msgs.msg import String, Bool

try:
    import edge_tts
except ImportError:
    edge_tts = None

try:
    from astro_audio.xtts_client import XttsClient, XttsError
except ImportError:  # paket kaynaktan çalıştırılıyorsa
    XttsClient = None

    class XttsError(RuntimeError):
        pass

try:
    import sounddevice as sd
except ImportError:
    sd = None

try:
    import scipy.io.wavfile as wav
except ImportError:
    wav = None

try:
    from dotenv import find_dotenv, load_dotenv
except ImportError:
    def find_dotenv(*args, **kwargs): return ""
    def load_dotenv(*args, **kwargs): pass


def _load_env():
    candidates = [
        os.path.abspath(".env"),
        os.path.abspath(os.path.join(os.getcwd(), ".env")),
        os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", ".env")),
        os.path.expanduser("~/Desktop/astr1/.env"),
        os.path.expanduser("~/.env")
    ]
    for c in candidates:
        if os.path.exists(c):
            load_dotenv(dotenv_path=c, override=False)
            return c
    try:
        env_path = find_dotenv(usecwd=True)
        if env_path:
            load_dotenv(dotenv_path=env_path, override=False)
            return env_path
    except Exception:
        pass
    return None


EMOJI_RE = re.compile(
    "["
    "\U0001F1E0-\U0001F1FF"
    "\U0001F300-\U0001F5FF"
    "\U0001F600-\U0001F64F"
    "\U0001F680-\U0001F6FF"
    "\U0001F700-\U0001F77F"
    "\U0001F780-\U0001F7FF"
    "\U0001F800-\U0001F8FF"
    "\U0001F900-\U0001F9FF"
    "\U0001FA00-\U0001FAFF"
    "\u2600-\u26FF"
    "\u2700-\u27BF"
    "]+",
    flags=re.UNICODE
)


def clean_tts_text(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r"(?i)<think>[\s\S]*?</think>", "", text)
    text = re.sub(r"(?i)<think>[\s\S]*", "", text)
    text = re.sub(r"(?i)</think>", "", text)
    text = EMOJI_RE.sub("", text)
    text = re.sub(r'```.*?```', '', text, flags=re.DOTALL)
    text = re.sub(r'`.*?`', '', text)
    text = re.sub(r'[\*\_\~\#\<\>]', '', text)
    text = " ".join(text.split())
    text = re.sub(r'\s+([,.:;?!])', r'\1', text)
    return text.strip()


def find_output_device() -> int | None:
    if not sd:
        return None
    try:
        devices = sd.query_devices()
        # 1. Look for hardware ReSpeaker output
        for i, dev in enumerate(devices):
            name = dev.get("name", "").lower()
            if dev.get("max_output_channels", 0) > 0:
                if any(k in name for k in ["respeaker", "uac1", "seeed", "arrayuac"]):
                    return i
        # 2. Fallback to system default output
        default_out = sd.default.device[1]
        if default_out >= 0:
            return default_out
    except Exception:
        pass
    return None


class TtsNode(Node):
    def __init__(self):
        super().__init__('tts_node')
        _load_env()

        self.tts_voice = os.getenv("TTS_VOICE", "tr-TR-AhmetNeural")
        self.tts_rate = os.getenv("TTS_RATE", "+20%")
        self.sample_rate = int(os.getenv("SAMPLE_RATE", "16000"))

        self.out_device_id = find_output_device()

        # Motor seçimi — tüm XTTS ayarları .env'den okunur (bkz. .env.example)
        self.engine = os.getenv("TTS_ENGINE", "edge-tts").strip().lower()
        self.language = os.getenv("TTS_LANGUAGE", "tr")
        self.xtts = None
        self.xtts_timeout = float(os.getenv("TTS_XTTS_TIMEOUT_S", "120"))

        if self.engine == "xtts":
            self._init_xtts()
        elif edge_tts is None:
            self.get_logger().error("❌ [TTS] edge_tts modülü kurulu değil!")

        # Publishers
        self.pub_speaking = self.create_publisher(Bool, '/tts/speaking', 10)

        # Subscribers
        self.sub_say = self.create_subscription(String, '/tts/say', self._on_say, 10)
        self.sub_interrupt = self.create_subscription(Bool, '/tts/interrupt', self._on_interrupt, 10)

        # Internal state
        self._speak_queue = queue.Queue()
        self._generation = 0
        self._generation_lock = threading.Lock()

        # Playback Thread
        self._playback_thread = threading.Thread(target=self._playback_loop, daemon=True)
        self._playback_thread.start()

        out_name = "default"
        if sd and self.out_device_id is not None:
            try:
                out_name = sd.query_devices(self.out_device_id)['name']
            except Exception:
                pass
        self.get_logger().info(f"🔊 [TTS Node] Hazır! Ses: {self.tts_voice} | Çıkış: [{self.out_device_id}] {out_name}")

    # ------------------------------------------------------------------
    # XTTS — kalıcı işçi süreci, arka planda ısınır (bkz. xtts_client.py)
    # ------------------------------------------------------------------
    def _resolve_speaker_wav(self, xtts_home: str) -> str:
        """Referans sesi sırayla arar: .env → paket payı → XTTS deposu."""
        configured = os.getenv("TTS_XTTS_SPEAKER_WAV", "")
        if configured:
            if os.path.exists(configured):
                return configured
            self.get_logger().warn(
                f"TTS_XTTS_SPEAKER_WAV bulunamadı ({configured}) — paketteki varsayılan sese düşülüyor"
            )

        try:
            from ament_index_python.packages import get_package_share_directory

            packaged = os.path.join(get_package_share_directory("astro_audio"), "voices", "astro.wav")
            if os.path.exists(packaged):
                return packaged
        except Exception:  # noqa: BLE001 — paket payı yoksa depodaki örneğe düşeriz
            pass

        return os.path.join(xtts_home, "Recording.wav") if xtts_home else ""

    def _init_xtts(self):
        if XttsClient is None:
            self.get_logger().error("xtts_client modülü yüklenemedi — edge-tts'e düşülüyor")
            self._downgrade_to_edge()
            return

        xtts_home = os.getenv("TTS_XTTS_HOME", "") or os.path.expanduser("~/.astro/tts")
        speaker_wav = self._resolve_speaker_wav(xtts_home)

        self.xtts = XttsClient(
            speaker_wav=speaker_wav,
            home=xtts_home,
            language=self.language,
            device=os.getenv("TTS_XTTS_DEVICE", "auto"),
            half=os.getenv("TTS_XTTS_HALF", "1") not in ("0", "false", "False"),
            batch_size=int(os.getenv("TTS_XTTS_BATCH_SIZE", "4")),
            model_dir=os.getenv("TTS_XTTS_MODEL_DIR", "") or None,
            checkpoint=os.getenv("TTS_XTTS_CHECKPOINT", "") or None,
            config=os.getenv("TTS_XTTS_CONFIG", "") or None,
            vocab=os.getenv("TTS_XTTS_VOCAB", "") or None,
            speakers=os.getenv("TTS_XTTS_SPEAKERS", "") or None,
            logger=self._xtts_log,
        )

        problem = self.xtts.check_install()
        if problem:
            self.get_logger().error(f"XTTS kullanılamıyor — {problem}")
            self.xtts = None
            self._downgrade_to_edge()
            return

        try:
            self.xtts.start()
        except XttsError as exc:
            self.get_logger().error(f"XTTS başlatılamadı: {exc}")
            self.xtts = None
            self._downgrade_to_edge()
            return

        if self.xtts.custom_model:
            self.get_logger().info(
                f"⏳ [TTS] XTTS yükleniyor — kendi modeliniz: "
                f"{self.xtts.custom_model['checkpoint']} "
                f"(referans ses: {os.path.basename(speaker_wav)})"
            )
        else:
            self.get_logger().info(
                f"⏳ [TTS] XTTS yükleniyor (hazır xtts_v2, referans ses: "
                f"{os.path.basename(speaker_wav)}) — model ilk çalıştırmada "
                "indirilirse birkaç dakika sürebilir"
            )
        # Model yüklemesi uzun sürüyor; düğüm bu sırada spin edebilmeli.
        threading.Thread(target=self._await_xtts_ready, daemon=True).start()

    def _await_xtts_ready(self):
        try:
            info = self.xtts.wait_ready(float(os.getenv("TTS_XTTS_STARTUP_TIMEOUT_S", "300")))
        except XttsError as exc:
            self.get_logger().error(f"XTTS hazır değil: {exc} — konuşmalar edge-tts ile yapılacak")
            self.xtts = None
            return
        model_label = "kendi modeliniz" if info.get("custom_model") else "hazır xtts_v2"
        self.get_logger().info(
            f"✅ [TTS] XTTS hazır ({model_label}, cihaz: {info.get('device')}"
            f"{', fp16' if info.get('half') else ''}"
            f"{', ' + info['gpu'] if info.get('gpu') else ''})"
        )

    def _xtts_log(self, level: str, message: str):
        getattr(self.get_logger(), level, self.get_logger().debug)(message)

    def _downgrade_to_edge(self):
        """XTTS yoksa sistemi konuşur hâlde tutan yedeğe geç."""
        self.engine = "edge-tts"
        if edge_tts is None:
            self.get_logger().error("❌ [TTS] edge_tts modülü de kurulu değil — TTS devre dışı")
        else:
            self.get_logger().warn(f"↩️  [TTS] edge-tts'e düşüldü (Ses: {self.tts_voice})")

    def _on_say(self, msg: String):
        text = clean_tts_text(msg.data)
        if text:
            self._speak_queue.put(text)

    def _on_interrupt(self, msg: Bool):
        if msg.data:
            with self._generation_lock:
                self._generation += 1
            while not self._speak_queue.empty():
                try:
                    self._speak_queue.get_nowait()
                except queue.Empty:
                    break
            if sd is not None:
                try:
                    sd.stop()
                except Exception:
                    pass

    def _set_speaking(self, state: bool):
        msg = Bool()
        msg.data = state
        self.pub_speaking.publish(msg)

    def _playback_loop(self):
        while rclpy.ok():
            try:
                text = self._speak_queue.get(timeout=0.05)
                self._synthesize_and_play(text)
            except queue.Empty:
                continue
            except Exception as e:
                self.get_logger().error(f"Playback loop hatası: {e}")

    def _synthesize_to_wav(self, text: str, mp3_path: str, wav_path: str) -> bool:
        """Metni `wav_path`'e sentezler. Üretim başarısızsa False döner.

        XTTS 24 kHz int16 WAV yazar; çalma yolu dosyanın kendi hızını okuduğu için
        yeniden örnekleme gerekmez.
        """
        if self.engine == "xtts":
            if self.xtts is not None and self.xtts.info and not self.xtts.is_alive:
                # İşçi ısındıktan sonra ölmüş (OOM, kill, çökme). Bir kez bildir ve bırak.
                self.get_logger().error(
                    f"XTTS süreci sonlandı (kod {self.xtts.returncode}) — "
                    "kalan konuşmalar edge-tts ile yapılacak"
                )
                self.xtts = None

            if self.xtts is not None and self.xtts.is_ready:
                try:
                    result = self.xtts.synthesize(
                        text, wav_path, timeout=self.xtts_timeout, language=self.language
                    )
                    self.get_logger().debug(
                        f"[xtts] {result.get('seconds')} sn ses, RTF {result.get('rtf')}"
                    )
                    return True
                except XttsError as exc:
                    self.get_logger().error(f"XTTS hatası: {exc}")
            elif self.xtts is not None:
                self.get_logger().warn("XTTS henüz ısınmadı — bu cümle edge-tts ile söyleniyor")

            if edge_tts is None:
                self.get_logger().error("Kullanılabilir yedek TTS motoru yok")
                return False

        communicate = edge_tts.Communicate(text, self.tts_voice, rate=self.tts_rate)
        asyncio.run(communicate.save(mp3_path))
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-i", mp3_path,
             "-ar", str(self.sample_rate), "-ac", "1", "-f", "wav", wav_path],
            check=True,
        )
        return True

    def _synthesize_and_play(self, text: str):
        with self._generation_lock:
            current_gen = self._generation

        if self.engine != "xtts" and edge_tts is None:
            return

        fd_mp3, mp3_path = tempfile.mkstemp(suffix=".mp3")
        fd_wav, wav_path = tempfile.mkstemp(suffix=".wav")
        os.close(fd_mp3)
        os.close(fd_wav)

        try:
            self.get_logger().info(f'🔊 [TTS Okuyor]: "{text}"')

            # 1-2. Sentez: XTTS doğrudan WAV üretir, edge-tts mp3 üretip ffmpeg ile çevirir
            if not self._synthesize_to_wav(text, mp3_path, wav_path):
                return

            with self._generation_lock:
                if current_gen != self._generation:
                    return

            # 3. Read and Play via sounddevice
            played = False
            if wav is not None and sd is not None:
                try:
                    rate, data = wav.read(wav_path)
                    with self._generation_lock:
                        if current_gen != self._generation:
                            return

                    self._set_speaking(True)
                    # Try selected device first, fallback to default
                    try:
                        sd.play(data, samplerate=rate, device=self.out_device_id, blocking=True)
                        played = True
                    except Exception as sd_err:
                        self.get_logger().warn(f"Cihaz {self.out_device_id} açılamadı ({sd_err}), default deneniyor...")
                        sd.play(data, samplerate=rate, device=None, blocking=True)
                        played = True
                except Exception as e:
                    self.get_logger().warn(f"sounddevice oynatma hatası: {e}")
                finally:
                    self._set_speaking(False)

            # 4. Fallback to system players if sounddevice failed
            if not played:
                self._set_speaking(True)
                for player in [["paplay", wav_path], ["aplay", "-D", "default", wav_path], ["ffplay", "-nodisp", "-autoexit", wav_path]]:
                    try:
                        subprocess.run(player, stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL, check=True)
                        played = True
                        break
                    except Exception:
                        pass
                self._set_speaking(False)

        except Exception as e:
            self.get_logger().error(f"TTS Sentez Hatası: {e}")
            self._set_speaking(False)
        finally:
            try:
                if os.path.exists(mp3_path):
                    os.remove(mp3_path)
                if os.path.exists(wav_path):
                    os.remove(wav_path)
            except Exception:
                pass


def main(args=None):
    rclpy.init(args=args)
    node = TtsNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        with node._generation_lock:
            node._generation += 1
        if node.xtts is not None:
            node.xtts.stop()
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
