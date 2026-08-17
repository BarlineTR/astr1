#!/usr/bin/env python3
"""ASTRO V1 — Text-to-Speech Node.

Supports five engines selectable via TTS_ENGINE env var:
  * elevenlabs — Most natural cloud voices (API key + internet)
  * edge-tts   — High-quality Microsoft Neural voices (requires internet)
  * xtts       — Local Coqui XTTS v2 voice cloning, offline, GPU recommended
  * pyttsx3    — Offline robotic fallback
  * gtts       — Google TTS (requires internet)

xtts, XTTS deposunun kendi venv'inde ayrı bir süreç olarak çalışır
(bkz. xtts_client.py, scripts/install_xtts.sh) — bu yorumlayıcıya kurulamaz.
"""
import os
import shutil
import subprocess
import tempfile
import threading

import rclpy
from rclpy.node import Node
from std_msgs.msg import Bool, String

try:
    import pyttsx3
except ImportError:
    pyttsx3 = None

try:
    from astro_audio.xtts_client import XttsClient, XttsError
except ImportError:  # paket kaynaktan çalıştırılıyorsa
    XttsClient = None

    class XttsError(RuntimeError):
        pass

try:
    import edge_tts
    import asyncio
except ImportError:
    edge_tts = None

try:
    from dotenv import load_dotenv, find_dotenv
except ImportError:
    load_dotenv = None
    find_dotenv = None


class TtsNode(Node):
    def __init__(self):
        super().__init__("tts_node")

        # Load repo-root .env before reading TTS_ENGINE / ElevenLabs keys
        if load_dotenv is not None:
            env_path = find_dotenv(usecwd=True) if find_dotenv else None
            if env_path:
                load_dotenv(env_path, override=False)

        # ROS parameters — defaults pulled from environment
        self.declare_parameter("engine", os.getenv("TTS_ENGINE", "edge-tts"))
        self.declare_parameter("voice", os.getenv("TTS_VOICE", "tr-TR-AhmetNeural"))
        self.declare_parameter("language", "tr")
        self.declare_parameter("rate", 150)
        self.declare_parameter("volume", 0.8)
        self.declare_parameter("elevenlabs_api_key", os.getenv("ELEVENLABS_API_KEY", ""))
        self.declare_parameter("elevenlabs_voice_id", os.getenv("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM"))
        self.declare_parameter("elevenlabs_model_id", os.getenv("ELEVENLABS_MODEL_ID", "eleven_multilingual_v2"))

        # XTTS (yerel ses klonlama) — ayrı venv'de çalışır
        self.declare_parameter("xtts_home", os.getenv("TTS_XTTS_HOME", ""))
        self.declare_parameter("xtts_speaker_wav", os.getenv("TTS_XTTS_SPEAKER_WAV", ""))
        self.declare_parameter("xtts_device", os.getenv("TTS_XTTS_DEVICE", "auto"))
        self.declare_parameter("xtts_half", os.getenv("TTS_XTTS_HALF", "1") not in ("0", "false", "False"))
        self.declare_parameter("xtts_batch_size", int(os.getenv("TTS_XTTS_BATCH_SIZE", "4")))
        self.declare_parameter("xtts_startup_timeout_s", 300.0)
        self.declare_parameter("xtts_timeout_s", 120.0)
        # Kendi eğittiğiniz XTTS modeli — boş bırakılırsa hazır xtts_v2 indirilir
        self.declare_parameter("xtts_model_dir", os.getenv("TTS_XTTS_MODEL_DIR", ""))
        self.declare_parameter("xtts_checkpoint", os.getenv("TTS_XTTS_CHECKPOINT", ""))
        self.declare_parameter("xtts_config", os.getenv("TTS_XTTS_CONFIG", ""))
        self.declare_parameter("xtts_vocab", os.getenv("TTS_XTTS_VOCAB", ""))
        self.declare_parameter("xtts_speakers", os.getenv("TTS_XTTS_SPEAKERS", ""))

        self.engine_name = self.get_parameter("engine").value
        self.voice_name = self.get_parameter("voice").value
        self.language = self.get_parameter("language").value
        self.rate = int(self.get_parameter("rate").value)
        self.volume = float(self.get_parameter("volume").value)

        # Publishers / subscribers
        self.pub_speaking = self.create_publisher(Bool, "/tts/speaking", 10)
        self.sub = self.create_subscription(String, "/tts/say", self._say_callback, 10)

        self.speaking = False
        self._speak_lock = threading.Lock()
        self.tts_engine = None
        self.xtts = None

        # Engine init
        if self.engine_name == "xtts":
            self._init_xtts()
        elif self.engine_name == "elevenlabs":
            self.get_logger().info(
                f"✅ [TTS] ElevenLabs motoru seçildi (Ses: {self.get_parameter('elevenlabs_voice_id').value})"
            )
        elif self.engine_name == "edge-tts":
            if edge_tts is None:
                self.get_logger().warn(
                    "edge-tts paketi kurulu değil, pyttsx3'e düşürülüyor. "
                    "Kurmak için: pip3 install edge-tts"
                )
                self.engine_name = "pyttsx3"
                self._init_pyttsx3()
            else:
                self.get_logger().info(
                    f"✅ [TTS] edge-tts hazır (Ses: {self.voice_name})"
                )
        elif self.engine_name == "pyttsx3":
            self._init_pyttsx3()
        elif self.engine_name == "gtts":
            self.get_logger().info("✅ [TTS] gTTS motoru seçildi (internet gerekli)")
        else:
            self.get_logger().error(f"Bilinmeyen TTS motoru: {self.engine_name}")

    # ------------------------------------------------------------------
    # pyttsx3 setup
    # ------------------------------------------------------------------
    def _init_pyttsx3(self):
        if pyttsx3 is None:
            self.get_logger().error("pyttsx3 kurulu değil — TTS devre dışı")
            return
        self.tts_engine = pyttsx3.init()
        self.tts_engine.setProperty("rate", self.rate)
        self.tts_engine.setProperty("volume", self.volume)
        for voice in self.tts_engine.getProperty("voices"):
            if self.language in voice.id.lower() or self.language in voice.name.lower():
                self.tts_engine.setProperty("voice", voice.id)
                break
        self.get_logger().info("✅ [TTS] pyttsx3 hazır")

    # ------------------------------------------------------------------
    # XTTS setup — kalıcı işçi süreci, arka planda ısınır
    # ------------------------------------------------------------------
    def _resolve_speaker_wav(self, xtts_home: str) -> str:
        """Referans sesi sırayla arar: parametre → paket payı → XTTS deposu."""
        configured = self.get_parameter("xtts_speaker_wav").value
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

        xtts_home = self.get_parameter("xtts_home").value or os.path.expanduser("~/.astro/tts")
        speaker_wav = self._resolve_speaker_wav(xtts_home)

        self.xtts = XttsClient(
            speaker_wav=speaker_wav,
            home=xtts_home,
            language=self.language,
            device=self.get_parameter("xtts_device").value,
            half=bool(self.get_parameter("xtts_half").value),
            batch_size=int(self.get_parameter("xtts_batch_size").value),
            model_dir=self.get_parameter("xtts_model_dir").value or None,
            checkpoint=self.get_parameter("xtts_checkpoint").value or None,
            config=self.get_parameter("xtts_config").value or None,
            vocab=self.get_parameter("xtts_vocab").value or None,
            speakers=self.get_parameter("xtts_speakers").value or None,
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
            info = self.xtts.wait_ready(float(self.get_parameter("xtts_startup_timeout_s").value))
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
        if edge_tts is not None:
            self.engine_name = "edge-tts"
            self.get_logger().warn(f"↩️  [TTS] edge-tts'e düşüldü (Ses: {self.voice_name})")
        else:
            self.engine_name = "pyttsx3"
            self._init_pyttsx3()

    # ------------------------------------------------------------------
    # Speaking state management
    # ------------------------------------------------------------------
    def _set_speaking(self, state: bool):
        self.speaking = state
        msg = Bool()
        msg.data = state
        self.pub_speaking.publish(msg)

    # ------------------------------------------------------------------
    # Callback — spawn a thread so ROS spin is not blocked
    # ------------------------------------------------------------------
    def _say_callback(self, msg: String):
        text = msg.data.strip()
        if not text:
            return
        thread = threading.Thread(target=self._speak, args=(text,), daemon=True)
        thread.start()

    def _speak(self, text: str):
        with self._speak_lock:
            self._set_speaking(True)
            self.get_logger().info(f"🔊 [TTS] Söyleniyor: {text}")
            try:
                if self.engine_name == "xtts":
                    self._speak_xtts(text)
                elif self.engine_name == "elevenlabs":
                    self._speak_elevenlabs(text)
                elif self.engine_name == "edge-tts":
                    self._speak_edge_tts(text)
                elif self.engine_name == "pyttsx3" and self.tts_engine is not None:
                    self.tts_engine.say(text)
                    self.tts_engine.runAndWait()
                elif self.engine_name == "gtts":
                    self._speak_gtts(text)
                else:
                    self.get_logger().warn("Aktif TTS motoru yok")
            except Exception as e:
                self.get_logger().error(f"TTS hatası: {e}")
            finally:
                self._set_speaking(False)

    # ------------------------------------------------------------------
    # XTTS — sentez ayrı süreçte, çalma burada (konuşma durumu bizde)
    # ------------------------------------------------------------------
    def _speak_xtts(self, text: str):
        if self.xtts is not None and self.xtts.info and not self.xtts.is_alive:
            # İşçi ısındıktan sonra ölmüş (OOM, kill, çökme). Bir kez bildir ve bırak.
            self.get_logger().error(
                f"XTTS süreci sonlandı (kod {self.xtts.returncode}) — "
                "kalan konuşmalar yedek motorla yapılacak"
            )
            self.xtts = None

        if self.xtts is None or not self.xtts.is_ready:
            if self.xtts is not None:
                self.get_logger().warn("XTTS henüz ısınmadı — bu cümle yedek motorla söyleniyor")
            self._fallback_speak(text)
            return

        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                tmp_path = f.name
            result = self.xtts.synthesize(
                text,
                tmp_path,
                timeout=float(self.get_parameter("xtts_timeout_s").value),
                language=self.language,
            )
            self.get_logger().debug(
                f"[xtts] {result.get('seconds')} sn ses, RTF {result.get('rtf')}"
            )
            self._play_wav(tmp_path)
        except XttsError as exc:
            self.get_logger().error(f"XTTS hatası: {exc}")
            if not self.xtts.is_alive:
                self.get_logger().error("XTTS süreci öldü — kalan konuşmalar yedek motorla yapılacak")
                self.xtts = None
            self._fallback_speak(text)
        finally:
            if tmp_path and os.path.exists(tmp_path):
                os.remove(tmp_path)

    def _fallback_speak(self, text: str):
        """XTTS kullanılamadığında robotun sessiz kalmaması için yedek motor."""
        if edge_tts is not None:
            self._speak_edge_tts(text)
            return
        if self.tts_engine is None:
            self._init_pyttsx3()
        if self.tts_engine is not None:
            self.tts_engine.say(text)
            self.tts_engine.runAndWait()
        else:
            self.get_logger().error("Kullanılabilir yedek TTS motoru yok")

    def _play_wav(self, path: str):
        """WAV çalar; mpg123 MP3'e özeldir, XTTS çıktısı WAV üretir."""
        players = (
            ("paplay", [path]),
            ("pw-play", [path]),
            ("aplay", ["-q", path]),
            ("ffplay", ["-nodisp", "-autoexit", "-loglevel", "quiet", path]),
        )
        for name, args in players:
            exe = shutil.which(name)
            if exe is None:
                continue
            if subprocess.run([exe, *args], capture_output=True).returncode == 0:
                return
            self.get_logger().debug(f"{name} çalamadı, sıradaki deneniyor")
        self.get_logger().error(
            "Ses çalınamadı — paplay/aplay/ffplay bulunamadı. Kurun: sudo apt install alsa-utils"
        )

    def _speak_elevenlabs(self, text: str):
        api_key = self.get_parameter("elevenlabs_api_key").value
        voice_id = self.get_parameter("elevenlabs_voice_id").value
        model_id = self.get_parameter("elevenlabs_model_id").value

        if not api_key:
            self.get_logger().error("ElevenLabs API Key bulunamadı! Lütfen .env dosyasını kontrol edin.")
            self._speak_edge_tts(text)
            return

        import requests
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
        headers = {
            "Accept": "audio/mpeg",
            "Content-Type": "application/json",
            "xi-api-key": api_key
        }
        data = {
            "text": text,
            "model_id": model_id,
            "voice_settings": {
                "stability": 0.5,
                "similarity_boost": 0.75
            }
        }

        tmp_path = None
        try:
            response = requests.post(url, json=data, headers=headers)
            if response.status_code != 200:
                self.get_logger().error(f"ElevenLabs API Hatası ({response.status_code}): {response.text}")
                self._speak_edge_tts(text)
                return

            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
                tmp_path = f.name
                f.write(response.content)

            subprocess.run(
                ["mpg123", "-q", tmp_path],
                check=True,
                capture_output=True,
            )
        except Exception as e:
            self.get_logger().error(f"ElevenLabs konuşma hatası: {e}")
            self._speak_edge_tts(text)
        finally:
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass

    # ------------------------------------------------------------------
    # edge-tts — uses the Python API directly (no CLI dependency)
    # ------------------------------------------------------------------
    def _speak_edge_tts(self, text: str):
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
                tmp_path = f.name

            # edge_tts is async; run in a temporary event loop
            async def _generate():
                communicate = edge_tts.Communicate(text, self.voice_name)
                await communicate.save(tmp_path)

            asyncio.run(_generate())

            # Play the generated audio
            subprocess.run(
                ["mpg123", "-q", tmp_path],
                check=True,
                capture_output=True,
            )
        except FileNotFoundError:
            self.get_logger().error(
                "mpg123 bulunamadı. Kurmak için: sudo apt install mpg123"
            )
        except Exception as e:
            self.get_logger().error(f"edge-tts hatası: {e}")
        finally:
            if tmp_path and os.path.exists(tmp_path):
                os.remove(tmp_path)

    # ------------------------------------------------------------------
    # gTTS fallback
    # ------------------------------------------------------------------
    def _speak_gtts(self, text: str):
        from gtts import gTTS

        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
                tmp_path = f.name
            tts = gTTS(text=text, lang=self.language)
            tts.save(tmp_path)
            subprocess.run(
                ["mpg123", "-q", tmp_path],
                check=True,
                capture_output=True,
            )
        finally:
            if tmp_path and os.path.exists(tmp_path):
                os.remove(tmp_path)


def main():
    rclpy.init()
    node = TtsNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        if node.xtts is not None:
            node.xtts.stop()
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
