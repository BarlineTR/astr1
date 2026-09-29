#!/usr/bin/env python3
"""ASTRO V1 — Resmi Robot Ağ Geçidi İstemcisi, Canlı Kamera ve Bilinç Telemetri Dashboard'u.

Bu servis iki temel görevi birlikte yürütür:
1. ASTRO BİLİNÇ VE TELEMETRİ DASHBOARD'U (Port 8080):
   - OAK-D RGB / Yüz kamerasından gerçek zamanlı, ultra düşük gecikmeli MJPEG canlı video akışı.
   - Kamera kopsa bile bağlantıyı düşürmeyen akıllı standby / reconnect fallback mekanizması.
   - Görsel Takip (Visual Tracking): Yüz kutuları (bbox), tanınan isimler, güven skoru, kişi sayısı, mesafe.
   - Biyometrik Kimlik (Identity): Verified/unverified, aktif konuşmacı, kimlik kaynağı, tanınma skoru.
   - Robot Durumu: State machine (IDLE, LISTENING, THINKING, SPEAKING, TRACKING), kafa açıları (hedef vs gerçek).
   - Ses / Konuşma Telemetrisi: Canlı RMS seviyesi, VAD durumu/güveni, barge-in durumu, self-voice skoru, DoA açısı.
   - AI / Diyalog Durumu: Model (4o-mini / Realtime), son kullanıcı cümlesi, robot cevabı, gecikme metrikleri (TTFT, TTFA, E2E).
   - Canlı Olay Akışı (Event Stream): Zaman damgalı olay kaydı (WAKE, RECOG, BARGE-IN, STATE).

2. RESMİ WEB KÖPRÜSÜ (Fastify Gateway: 8420 & Next.js: 3000):
   - Fastify Ağ Geçidi ile WebSocket telemetri köprüsü kurar.
   - Web panelinden gelen kafa hedef açısı, e-stop ve yapılandırma güncellemelerini ROS 2'ye iletir.
"""

import argparse
import asyncio
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
import os
from pathlib import Path
import sys
import threading
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

try:
    import cv2
    import numpy as np
    HAVE_CV2 = True
except ImportError:
    HAVE_CV2 = False

try:
    import websockets
    import websockets.exceptions
    HAVE_WEBSOCKETS = True
except ImportError:
    HAVE_WEBSOCKETS = False

# ROS 2 Kütüphaneleri
HAVE_ROS2 = False
try:
    import rclpy
    from rclpy.node import Node
    from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy, qos_profile_sensor_data
    from std_msgs.msg import String as RosString, Float32 as RosFloat32, Bool as RosBool, Int32 as RosInt32
    try:
        from sensor_msgs.msg import Image as RosImage, CompressedImage as RosCompressedImage
    except ImportError:
        RosImage = None
        RosCompressedImage = None
    try:
        from astro_base.msg import HeadState as RosHeadState, HeadCmd as RosHeadCmd
    except ImportError:
        RosHeadState = None
        RosHeadCmd = None
    HAVE_ROS2 = True
except ImportError:
    pass

TOKEN_FILE = Path(os.path.expanduser("~/.astro/device_token.json"))
PROTOCOL_VERSION = "1"

RECONNECT_BASLANGIC_S = 2.0
RECONNECT_MAKSIMUM_S  = 60.0
RECONNECT_CARPAN      = 2.0


def jeton_yukle() -> dict:
    if TOKEN_FILE.exists():
        try:
            with open(TOKEN_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def jeton_kaydet(veri: dict):
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(TOKEN_FILE, "w", encoding="utf-8") as f:
        json.dump(veri, f, indent=2)


def cihaz_eslestir(site_url: str, serial: str, kod: str) -> dict:
    url = f"{site_url.rstrip('/')}/api/cihaz/eslestir"
    payload = json.dumps({"serial": serial, "kod": kod, "firmware": "astro-v1.0"}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json", "User-Agent": "AstroRobotAgent/1.0"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            print(f"✅ Robot başarıyla eşleştirildi! Cihaz ID: {data.get('cihazId')}")
            return data
    except urllib.error.HTTPError as e:
        hata_metni = e.read().decode("utf-8")
        print(f"❌ Eşleştirme hatası ({e.code}): {hata_metni}")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Siteye bağlanılamadı ({url}): {e}")
        sys.exit(1)


class AstroRobotAjan:
    def __init__(
        self,
        token: Optional[str] = None,
        gecit_url: str = "ws://127.0.0.1:8420",
        serial: str = "ASTRO-V1-000123",
        site_url: str = "http://127.0.0.1:3000",
        dashboard_port: int = 8080,
    ):
        self.token = token
        self.gecit_url = gecit_url.rstrip("/") if gecit_url else ""
        self.site_url = site_url.rstrip("/") if site_url else ""
        self.serial = serial
        self.dashboard_port = dashboard_port
        self.ws = None
        self.calisiyor = True
        self._lock = threading.Lock()

        # Telemetri durumu
        self.kabul_edildi: Optional[asyncio.Event] = None
        self.hedef_yaw = 0.0
        self.gercek_yaw = 0.0
        self.encoder_ok = True
        self.watchdog_ok = True
        self.estop = False
        self.doa_deg = 0.0
        self.doa_confidence = 0.0
        self.vad = False
        self.gaze_state = "IDLE"
        self.attention_owner = "none"
        self.visual_valid = False
        self.faces_list: List[Dict[str, Any]] = []
        self.person_count = 0
        self.son_konusma = ""
        self.son_konusma_zaman = 0.0
        self.son_robot_cevabi = ""
        self.robot_duygu = "neutral"
        self.realtime_state = "IDLE"
        self.robot_state = "IDLE"
        self.voice_mode = "4O"
        self.is_speaking = False
        self.is_sleeping = False

        # Kimlik ve konuşmacı
        self.aktif_muhatap = "Misafir"
        self.aktif_muhatap_zaman = 0.0
        self.biyometrik_kimlik = "Bilinmiyor"
        self.kimlik_dogrulandi = False
        self.kimlik_kaynagi = "guest_unidentified"
        self.kimlik_skoru = 0.0

        # Akustik telemetri
        self.mic_rms = 0.0
        self.ambient_rms = 0.0
        self.self_voice_score = 0.0
        self.barge_in_active = False
        self.playback_active = False

        # AI & Diyalog Metrikleri
        self.current_model = "gpt-4o-mini"
        self.llm_ttft_ms = 0.0
        self.llm_total_ms = 0.0
        self.tts_ttfa_ms = 0.0
        self.tts_total_ms = 0.0
        self.e2e_playback_ms = 0.0

        # Kamera kareleri
        self.latest_jpeg: Optional[bytes] = None
        self.latest_jpeg_time = 0.0
        self.camera_fps = 0.0
        self._frame_counter = 0
        self._fps_timer = time.time()

        # Olay kaydı (Event Stream)
        self.events: List[Dict[str, Any]] = []
        self._add_event("SYSTEM", "Astro Web Köprüsü ve Bilinç Konsolu başlatıldı.")

        # Ayar senkronizasyonu
        self.son_ayar_guncelleme = ""

        # ROS 2 Entegrasyonu
        self.ros_node = None
        self._ros_thread = None
        self._init_ros()

        # Dahili HTTP / MJPEG Dashboard Sunucusu
        self.http_server = None
        self._start_http_dashboard_server()

    def _add_event(self, category: str, message: str, meta: Optional[Dict[str, Any]] = None):
        """Thread-safe olay akışı kaydı."""
        with self._lock:
            evt = {
                "id": int(time.time() * 1000),
                "time": time.strftime("%H:%M:%S"),
                "timestamp": time.time(),
                "category": category,
                "message": message,
                "meta": meta or {},
            }
            self.events.append(evt)
            if len(self.events) > 80:
                self.events = self.events[-80:]

    def _init_ros(self):
        """ROS 2 abonelikleri ve yayıncıları başlatır."""
        if not HAVE_ROS2:
            print("⚠️ ROS 2 (rclpy) bulunamadı. Simülasyon modunda çalışılıyor.")
            return

        try:
            if not rclpy.ok():
                rclpy.init(args=None)

            self.ros_node = Node("astro_web_bridge")
            print("🤖 ROS 2 Düğümü oluşturuldu: /astro_web_bridge")

            # Yayıncılar
            self.pub_head_cmd_pos = self.ros_node.create_publisher(RosFloat32, "/head/cmd_pos", 10)
            self.pub_safety_estop = self.ros_node.create_publisher(RosBool, "/safety/emergency_stop", 10)
            self.pub_config_update = self.ros_node.create_publisher(RosString, "/astro/config_update", 10)
            self.pub_quiet_mode = self.ros_node.create_publisher(RosBool, "/astro/quiet_mode", 10)
            self.pub_sleep_mode = self.ros_node.create_publisher(RosBool, "/astro/sleep_mode", 10)
            self.pub_sys_sleep = self.ros_node.create_publisher(RosBool, "/system/sleep", 10)
            if RosHeadCmd is not None:
                self.pub_head_cmd = self.ros_node.create_publisher(RosHeadCmd, "/head/command", 10)
            else:
                self.pub_head_cmd = None

            # Abonelikler
            if RosHeadState is not None:
                self.ros_node.create_subscription(RosHeadState, "/head/state", self._on_head_state, 10)
            self.ros_node.create_subscription(RosFloat32, "/head/yaw_deg", self._on_head_yaw_deg, 10)
            self.ros_node.create_subscription(RosFloat32, "/audio/doa", self._on_audio_doa, 10)
            self.ros_node.create_subscription(RosBool, "/audio/vad", self._on_audio_vad, 10)
            self.ros_node.create_subscription(RosFloat32, "/audio/doa_confidence", self._on_audio_confidence, 10)
            self.ros_node.create_subscription(RosString, "/vision/faces", self._on_vision_faces, 10)
            self.ros_node.create_subscription(RosInt32, "/vision/person_count", self._on_person_count, 10)
            self.ros_node.create_subscription(RosString, "/gaze/state", self._on_gaze_state, 10)
            self.ros_node.create_subscription(RosBool, "/safety/emergency_stop", self._on_safety_estop, 10)
            self.ros_node.create_subscription(RosString, "/speech/text", self._on_speech_text, 10)
            self.ros_node.create_subscription(RosString, "/speech/response", self._on_speech_response, 10)
            self.ros_node.create_subscription(RosString, "/robot/emotion", self._on_robot_emotion, 10)
            self.ros_node.create_subscription(RosString, "/astro/telemetry", self._on_astro_telemetry, 10)
            self.ros_node.create_subscription(RosString, "/astro/turn_telemetry", self._on_turn_telemetry, 10)
            self.ros_node.create_subscription(RosString, "/astro/dispatched_transcript", self._on_speech_text, 10)

            # Canlı Kamera Görüntüsü Abonelikleri (Sensör verisi için BEST_EFFORT qos_profile_sensor_data)
            cam_qos = qos_profile_sensor_data if 'qos_profile_sensor_data' in globals() else QoSProfile(depth=5, reliability=ReliabilityPolicy.BEST_EFFORT)
            if RosImage is not None:
                self.ros_node.create_subscription(RosImage, "/oak/rgb/image_raw", self._on_camera_raw, cam_qos)
                self.ros_node.create_subscription(RosImage, "/vision/face_image", self._on_camera_raw, cam_qos)
            if RosCompressedImage is not None:
                self.ros_node.create_subscription(RosCompressedImage, "/oak/rgb/image_raw/compressed", self._on_camera_compressed, cam_qos)

            self._ros_thread = threading.Thread(target=self._ros_spin_loop, daemon=True)
            self._ros_thread.start()
            print("🚀 ROS 2 Konuları dinleniyor (/oak/rgb/image_raw, /astro/telemetry, /head/state, /audio/doa...)")
        except Exception as e:
            print(f"⚠️ ROS 2 başlatma hatası: {e}. Simülasyona devam ediliyor.")

    def _ros_spin_loop(self):
        try:
            rclpy.spin(self.ros_node)
        except Exception:
            pass

    # --- ROS 2 Geri Çağrıları ---

    def _on_camera_raw(self, msg):
        """OAK-D ham RGB karesini MJPEG JPEG'e dönüştürür."""
        if not HAVE_CV2:
            return
        try:
            h, w = msg.height, msg.width
            enc = msg.encoding.lower()
            if enc in ("rgb8", "bgr8"):
                arr = np.frombuffer(msg.data, dtype=np.uint8).reshape((h, w, 3))
                if enc == "rgb8":
                    arr = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
                success, encoded = cv2.imencode(".jpg", arr, [cv2.IMWRITE_JPEG_QUALITY, 75])
                if success:
                    with self._lock:
                        self.latest_jpeg = encoded.tobytes()
                        self.latest_jpeg_time = time.time()
                        self._frame_counter += 1
                        now = time.time()
                        if now - self._fps_timer >= 1.0:
                            self.camera_fps = round(self._frame_counter / (now - self._fps_timer), 1)
                            self._frame_counter = 0
                            self._fps_timer = now
        except Exception:
            pass

    def _on_camera_compressed(self, msg):
        try:
            with self._lock:
                self.latest_jpeg = bytes(msg.data)
                self.latest_jpeg_time = time.time()
        except Exception:
            pass

    def _on_head_state(self, msg):
        try:
            pos = getattr(msg, "actual_yaw_deg", None)
            if pos is None or math.isnan(pos):
                pos = getattr(msg, "position_deg", None)
            if pos is None or math.isnan(pos):
                pos = getattr(msg, "estimated_yaw_deg", 0.0)
            if pos is not None and not math.isnan(pos):
                self.gercek_yaw = float(pos)

            tgt = getattr(msg, "target_position_deg", None)
            if tgt is not None and not math.isnan(tgt):
                self.hedef_yaw = float(tgt)

            self.encoder_ok = bool(getattr(msg, "encoder_valid", True))
            self.watchdog_ok = bool(getattr(msg, "watchdog_healthy", True))
        except Exception:
            pass

    def _on_head_yaw_deg(self, msg):
        try:
            val = float(msg.data)
            if not math.isnan(val):
                self.gercek_yaw = val
        except Exception:
            pass

    def _on_audio_doa(self, msg):
        try:
            val = float(msg.data)
            if not math.isnan(val):
                self.doa_deg = val
        except Exception:
            pass

    def _on_audio_vad(self, msg):
        try:
            prev = self.vad
            self.vad = bool(msg.data)
            if self.vad and not prev:
                self._add_event("AUDIO", f"Kullanıcı konuşması algılandı (VAD Onset, DoA: {self.doa_deg:.0f}°)")
        except Exception:
            pass

    def _on_audio_confidence(self, msg):
        try:
            self.doa_confidence = max(0.0, min(1.0, float(msg.data)))
        except Exception:
            pass

    def _on_person_count(self, msg):
        try:
            self.person_count = int(msg.data)
        except Exception:
            pass

    def _on_vision_faces(self, msg):
        try:
            raw = (msg.data or "").strip()
            if not raw:
                self.faces_list = []
                self.visual_valid = False
                return
            faces = json.loads(raw)
            if isinstance(faces, list) and len(faces) > 0:
                parsed = []
                for f in faces:
                    if not isinstance(f, dict):
                        continue
                    name = f.get("recognized_name") or f.get("name")
                    is_known = bool(f.get("is_known", False)) and str(name).lower() != "misafir"
                    conf = float(f.get("confidence", 0.0))

                    if not is_known:
                        name = "Misafir"
                        is_known = False

                    box = [
                        float(f.get("x", 0.2)),
                        float(f.get("y", 0.2)),
                        float(f.get("width", 0.3)),
                        float(f.get("height", 0.4)),
                    ]
                    dist = float(f.get("distance_m", 1.5) or 1.5)
                    parsed.append({
                        "name": name,
                        "is_known": is_known,
                        "confidence": round(conf, 2),
                        "box": [round(b, 3) for b in box],
                        "center": [round(box[0] + box[2] / 2.0, 3), round(box[1] + box[3] / 2.0, 3)],
                        "distance_m": round(dist, 2),
                        "looking_at_robot": bool(f.get("looking_at_robot", True)),
                        "head_pose_yaw": round(float(f.get("head_yaw", 0.0)), 1),
                    })
                self.faces_list = parsed
                self.visual_valid = len(parsed) > 0
                self.person_count = max(self.person_count, len(parsed))
                self.attention_owner = "visual"

                # Bilinen kişi ilk kez tespit edildiğinde olay kaydet
                known_names = [p["name"] for p in parsed if p["is_known"]]
                if known_names:
                    self._add_event("VISION", f"Yüz tanıma: {', '.join(known_names)} (Güven: %{int(parsed[0]['confidence']*100)})")
            else:
                self.faces_list = []
                self.visual_valid = False
                if self.attention_owner == "visual":
                    self.attention_owner = "audio" if self.vad else "none"
        except Exception:
            pass

    def _on_gaze_state(self, msg):
        try:
            self.gaze_state = str(msg.data).strip()
        except Exception:
            pass

    def _on_safety_estop(self, msg):
        try:
            self.estop = bool(msg.data)
            if self.estop:
                self._add_event("SAFETY", "ACİL DURDURMA (E-STOP) TETİKLENDİ 🛑")
        except Exception:
            pass

    def _on_speech_text(self, msg):
        try:
            txt = (msg.data or "").strip()
            if txt:
                self.son_konusma = txt
                self.son_konusma_zaman = time.time()
                self._add_event("STT", f"Kullanıcı: \"{txt}\"")
        except Exception:
            pass

    def _on_speech_response(self, msg):
        try:
            txt = (msg.data or "").strip()
            if txt:
                self.son_robot_cevabi = txt
                self._add_event("TTS", f"Astro: \"{txt}\"")
        except Exception:
            pass

    def _on_robot_emotion(self, msg):
        try:
            emo = (msg.data or "").strip()
            if emo:
                self.robot_duygu = emo
        except Exception:
            pass

    def _on_realtime_state(self, msg):
        try:
            st = (msg.data or "").strip()
            if st:
                self.realtime_state = st
        except Exception:
            pass

    def _on_astro_telemetry(self, msg):
        """Enrich telemetri JSON objesini doğrudan ROS 2 düğümünden alır."""
        try:
            d = json.loads(msg.data or "{}")
            with self._lock:
                if "robot_state" in d:
                    self.robot_state = str(d["robot_state"])
                if "voice_mode" in d:
                    self.voice_mode = str(d["voice_mode"])
                if "is_speaking" in d:
                    self.is_speaking = bool(d["is_speaking"])
                    self.playback_active = self.is_speaking
                if "is_sleeping" in d:
                    self.is_sleeping = bool(d["is_sleeping"])

                # Kimlik
                id_data = d.get("identity", {})
                if id_data:
                    self.aktif_muhatap = str(id_data.get("name", "Misafir"))
                    self.kimlik_dogrulandi = bool(id_data.get("is_known", False))
                    self.biyometrik_kimlik = str(id_data.get("biometric_status", "unknown"))
                    self.kimlik_kaynagi = str(id_data.get("identity_source", "guest"))
                    self.kimlik_skoru = float(id_data.get("confidence", 0.0))

                # Akustik
                aud = d.get("audio", {})
                if aud:
                    self.mic_rms = float(aud.get("mic_rms", 0.0))
                    self.ambient_rms = float(aud.get("ambient_rms", 0.0))
                    self.self_voice_score = float(aud.get("self_voice_score", 0.0))
                    self.barge_in_active = bool(aud.get("barge_in", False))

                # Diyalog & Konuşma
                conv = d.get("conversation", {})
                if conv:
                    self.current_model = str(conv.get("model", self.current_model))
                    u_utt = conv.get("last_user_utterance")
                    if u_utt and u_utt != self.son_konusma:
                        self.son_konusma = u_utt
                    a_rep = conv.get("last_assistant_response")
                    if a_rep and a_rep != self.son_robot_cevabi:
                        self.son_robot_cevabi = a_rep

                # Gecikme Metrikleri
                lat = d.get("latency", {})
                if lat:
                    self.llm_ttft_ms = float(lat.get("llm_ttft_ms", lat.get("p50_total_ms", 0.0)))
                    self.tts_ttfa_ms = float(lat.get("tts_ttfa_ms", 0.0))
                    self.e2e_playback_ms = float(lat.get("p50_total_ms", 0.0))
        except Exception:
            pass

    def _on_turn_telemetry(self, msg):
        """Doğrudan Astro Realtime Node'dan gelen tam turn telemetrisini işler."""
        try:
            d = json.loads(msg.data or "{}")
            with self._lock:
                if d.get("llm_model"):
                    self.current_model = str(d["llm_model"])
                if d.get("actual_provider"):
                    self.voice_mode = "4O"
                if "first_token_ms" in d and float(d.get("first_token_ms") or 0.0) > 0:
                    self.llm_ttft_ms = float(d["first_token_ms"])
                elif "llm_duration_ms" in d and float(d.get("llm_duration_ms") or 0.0) > 0:
                    self.llm_ttft_ms = float(d["llm_duration_ms"])
                if "tts_ttfa_ms" in d and float(d.get("tts_ttfa_ms") or 0.0) > 0:
                    self.tts_ttfa_ms = float(d["tts_ttfa_ms"])
                if "end_to_end_first_audio_ms" in d and float(d.get("end_to_end_first_audio_ms") or 0.0) > 0:
                    self.e2e_playback_ms = float(d["end_to_end_first_audio_ms"])
                u_turn = d.get("user_turn_id", "")
                self._add_event("AI", f"Turn Telemetrisi: {self.current_model} | E2E: {self.e2e_playback_ms:.0f}ms | TTFA: {self.tts_ttfa_ms:.0f}ms")
        except Exception:
            pass

    # --- Standby Test Kartı (Kamera Yokken Akışı Kesmeyen Fallback) ---

    def _generate_standby_frame(self) -> bytes:
        """Kamera akışı olmadığında gösterilen kompakt, profesyonel CAMERA OFFLINE kartı."""
        if not HAVE_CV2:
            return b""
        w, h = 640, 360
        img = np.zeros((h, w, 3), dtype=np.uint8)
        img[:] = (13, 17, 23)  # Dark slate background #0d1117

        # Compact center card box
        card_w, card_h = 320, 130
        x1 = (w - card_w) // 2
        y1 = (h - card_h) // 2
        x2 = x1 + card_w
        y2 = y1 + card_h
        cv2.rectangle(img, (x1, y1), (x2, y2), (28, 35, 48), -1)
        cv2.rectangle(img, (x1, y1), (x2, y2), (48, 54, 66), 1)

        # Status badge dot & text
        dot_cx = x1 + 35
        dot_cy = y1 + 45
        cv2.circle(img, (dot_cx, dot_cy), 6, (60, 60, 240), -1)  # Red/amber offline dot
        cv2.putText(img, "CAMERA OFFLINE", (dot_cx + 18, dot_cy + 6),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.65, (230, 237, 243), 2, cv2.LINE_AA)

        # Subtitle
        cv2.putText(img, "OAK-D Lite  *  Awaiting RGB Stream", (x1 + 32, y1 + 82),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.42, (139, 148, 158), 1, cv2.LINE_AA)

        # Micro timestamp
        cv2.putText(img, f"STANDBY {time.strftime('%H:%M:%S')}", (x1 + 32, y1 + 106),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.36, (80, 90, 105), 1, cv2.LINE_AA)

        success, enc = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 85])
        return enc.tobytes() if success else b""

    def get_latest_jpeg(self) -> bytes:
        """Son JPEG karesini veya hazır standby karesini döner."""
        with self._lock:
            if self.latest_jpeg and (time.time() - self.latest_jpeg_time) < 2.0:
                return self.latest_jpeg
        return self._generate_standby_frame()

    # --- Normalize Edilmiş Tekil Telemetri JSON Sözlüğü ---

    def get_normalized_telemetry(self) -> Dict[str, Any]:
        """Web paneli ve REST endpoint'ler için tam teşekküllü normalize telemetri objesi."""
        with self._lock:
            # Bilişsel durum hesaplaması
            cog_state = self.robot_state
            if self.is_speaking:
                cog_state = "SPEAKING"
            elif self.vad:
                cog_state = "LISTENING"
            elif self.realtime_state in ("THINKING", "RESPONDING"):
                cog_state = "THINKING"
            elif self.visual_valid:
                cog_state = "TRACKING"

            cam_alive = bool(self.latest_jpeg and (time.time() - self.latest_jpeg_time) < 2.5)

            return {
                "timestamp": time.time(),
                "time_str": time.strftime("%H:%M:%S"),
                "robot_state": cog_state,
                "voice_mode": self.voice_mode,
                "is_speaking": self.is_speaking,
                "is_sleeping": self.is_sleeping,
                "head": {
                    "desiredYawDeg": round(self.hedef_yaw, 1),
                    "actualYawDeg": round(self.gercek_yaw, 1),
                    "encoderOk": self.encoder_ok,
                },
                "visual_tracking": {
                    "camera_alive": cam_alive,
                    "camera_fps": self.camera_fps if cam_alive else 0.0,
                    "person_count": self.person_count,
                    "visual_presence": self.visual_valid or (self.person_count > 0),
                    "attention_owner": self.attention_owner,
                    "gaze_state": self.gaze_state,
                    "faces": self.faces_list,
                },
                "identity": {
                    "name": self.aktif_muhatap,
                    "display_name": self.aktif_muhatap,
                    "verified": self.kimlik_dogrulandi,
                    "biometric_status": self.biyometrik_kimlik,
                    "identity_source": self.kimlik_kaynagi,
                    "confidence": round(self.kimlik_skoru, 2),
                    "active_speaker": self.aktif_muhatap if self.vad else None,
                },
                "audio_speech": {
                    "vad": self.vad,
                    "speech_detected": self.vad,
                    "vad_confidence": round(self.doa_confidence, 2),
                    "mic_rms": round(self.mic_rms, 4),
                    "ambient_rms": round(self.ambient_rms, 4),
                    "doa_deg": round(self.doa_deg, 1) if self.vad else None,
                    "doa_confidence": round(self.doa_confidence, 2),
                    "self_voice_score": round(self.self_voice_score, 2),
                    "echo_suppression_active": self.is_speaking,
                    "playback_active": self.is_speaking,
                    "barge_in_active": self.barge_in_active,
                },
                "ai_conversation": {
                    "current_model": self.current_model,
                    "mode": self.voice_mode,
                    "last_user_utterance": self.son_konusma or None,
                    "last_assistant_response": self.son_robot_cevabi or None,
                    "llm_ttft_ms": round(self.llm_ttft_ms, 1),
                    "tts_ttfa_ms": round(self.tts_ttfa_ms, 1),
                    "e2e_playback_ms": round(self.e2e_playback_ms, 1),
                },
                "safety": {
                    "estop": self.estop,
                    "watchdog_ok": self.watchdog_ok,
                },
                "events": list(self.events[-15:]),
            }

    # --- Dahili HTTP Dashboard Sunucusu ---

    def _start_http_dashboard_server(self):
        agent_ref = self
        port = self.dashboard_port

        class ConsciousnessHandler(BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                pass  # Standart konsol kirliliğini engelle

            def do_HEAD(self):
                if self.path in ("/", "/dashboard"):
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.end_headers()
                elif self.path in ("/camera/stream.mjpg", "/camera/snapshot.jpg"):
                    self.send_response(200)
                    self.send_header("Content-Type", "image/jpeg")
                    self.end_headers()
                elif self.path == "/api/telemetry":
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.end_headers()
                else:
                    self.send_response(404)
                    self.end_headers()

            def do_GET(self):
                if self.path in ("/", "/dashboard"):
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.end_headers()
                    self.wfile.write(DASHBOARD_HTML.encode("utf-8"))

                elif self.path == "/camera/stream.mjpg":
                    self.send_response(200)
                    self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=--frame")
                    self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
                    self.send_header("Pragma", "no-cache")
                    self.send_header("Expires", "0")
                    self.end_headers()
                    try:
                        while agent_ref.calisiyor:
                            frame = agent_ref.get_latest_jpeg()
                            self.wfile.write(b"--frame\r\n")
                            self.wfile.write(b"Content-Type: image/jpeg\r\n")
                            self.wfile.write(f"Content-Length: {len(frame)}\r\n\r\n".encode("utf-8"))
                            self.wfile.write(frame)
                            self.wfile.write(b"\r\n")
                            time.sleep(0.05)  # 20 FPS
                    except (BrokenPipeError, ConnectionResetError):
                        pass

                elif self.path == "/camera/snapshot.jpg":
                    frame = agent_ref.get_latest_jpeg()
                    self.send_response(200)
                    self.send_header("Content-Type", "image/jpeg")
                    self.send_header("Content-Length", str(len(frame)))
                    self.end_headers()
                    self.wfile.write(frame)

                elif self.path == "/api/telemetry":
                    data = agent_ref.get_normalized_telemetry()
                    payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)

                elif self.path == "/api/events":
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.send_header("Cache-Control", "no-cache")
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.end_headers()
                    last_id = 0
                    try:
                        while agent_ref.calisiyor:
                            with agent_ref._lock:
                                evts = [e for e in agent_ref.events if e["id"] > last_id]
                            for e in evts:
                                last_id = e["id"]
                                msg = f"data: {json.dumps(e, ensure_ascii=False)}\n\n"
                                self.wfile.write(msg.encode("utf-8"))
                                self.wfile.flush()
                            time.sleep(0.2)
                    except (BrokenPipeError, ConnectionResetError):
                        pass

                else:
                    self.send_response(404)
                    self.end_headers()

            def do_POST(self):
                content_len = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(content_len).decode("utf-8") if content_len > 0 else "{}"
                try:
                    params = json.loads(body)
                except Exception:
                    params = {}

                if self.path == "/api/estop":
                    engaged = bool(params.get("engaged", not agent_ref.estop))
                    agent_ref.estop = engaged
                    if agent_ref.ros_node is not None:
                        try:
                            msg_b = RosBool()
                            msg_b.data = engaged
                            agent_ref.pub_safety_estop.publish(msg_b)
                        except Exception:
                            pass
                    agent_ref._add_event("SAFETY", f"E-Stop komutu uygulandı: {'DURDURULDU' if engaged else 'KALDIRILDI'}")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.end_headers()
                    self.wfile.write(json.dumps({"ok": True, "estop": engaged}).encode("utf-8"))

                elif self.path == "/api/head":
                    yaw = float(params.get("yaw_deg", 0.0))
                    agent_ref.hedef_yaw = max(-85.0, min(85.0, yaw))
                    if agent_ref.ros_node is not None:
                        try:
                            msg_f = RosFloat32()
                            msg_f.data = float(agent_ref.hedef_yaw)
                            agent_ref.pub_head_cmd_pos.publish(msg_f)
                        except Exception:
                            pass
                    agent_ref._add_event("HEAD", f"Kafa açısı komutu: {agent_ref.hedef_yaw:.1f}°")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.end_headers()
                    self.wfile.write(json.dumps({"ok": True, "hedef_yaw": agent_ref.hedef_yaw}).encode("utf-8"))

                else:
                    self.send_response(404)
                    self.end_headers()

        def _serve():
            try:
                server = ThreadingHTTPServer(("0.0.0.0", port), ConsciousnessHandler)
                print(f"✨ [Astro Consciousness Dashboard]: Canlı panel http://0.0.0.0:{port} adresinde yayında!")
                server.serve_forever()
            except Exception as e:
                print(f"⚠️ Dashboard HTTP sunucusu başlatılamadı: {e}")

        t = threading.Thread(target=_serve, daemon=True)
        t.start()

    # --- Fastify Ağ Geçidi Bağlantısı (Varsa Devam Eder) ---

    def _durum_sifirla(self):
        self.kabul_edildi = asyncio.Event()
        self.ws = None

    async def baglan_bir_kez(self) -> bool:
        if not HAVE_WEBSOCKETS or not self.token or not self.gecit_url:
            await asyncio.sleep(2.0)
            return True

        self._durum_sifirla()
        ws_url = f"{self.gecit_url}/ws/cihaz"
        print(f"🔌 Ağ geçidine bağlanılıyor: {ws_url} ...")

        try:
            async with websockets.connect(ws_url) as ws:
                self.ws = ws
                print("🚀 Ağ geçidi bağlantısı kuruldu.")

                merhaba = {
                    "kind": "cihaz.merhaba",
                    "v": PROTOCOL_VERSION,
                    "token": self.token,
                    "firmware": "astro-v1.0",
                }
                await ws.send(json.dumps(merhaba))

                await asyncio.gather(
                    self.mesaj_dinle(),
                    self.telemetri_dongusu(),
                    self.ayar_senkronizasyon_dongusu(),
                )
            return True

        except Exception as e:
            return True

    async def calistir(self):
        """Ajan ana çalışma döngüsü."""
        bekleme = RECONNECT_BASLANGIC_S
        while self.calisiyor:
            if not self.token:
                # Standalone developer dashboard mode
                await asyncio.sleep(1.0)
                continue

            t_baslangic = time.time()
            devam = await self.baglan_bir_kez()
            if not devam or not self.calisiyor:
                break
            if time.time() - t_baslangic > 30:
                bekleme = RECONNECT_BASLANGIC_S
            await asyncio.sleep(bekleme)
            bekleme = min(bekleme * RECONNECT_CARPAN, RECONNECT_MAKSIMUM_S)

    async def mesaj_dinle(self):
        try:
            async for ham_mesaj in self.ws:
                try:
                    mesaj = json.loads(ham_mesaj)
                except Exception:
                    continue

                tur = mesaj.get("kind")
                if tur == "gecit.kabul":
                    self.kabul_edildi.set()
                    print("✅ Ağ geçidi robotu kabul etti! Kontrol komutları ve telemetri devrede.")
                elif tur == "gecit.ping":
                    t_val = mesaj.get("t", int(time.time() * 1000))
                    await self.ws.send(json.dumps({"kind": "cihaz.pong", "t": t_val}))
                elif tur == "gecit.komut":
                    await self.komut_isle(mesaj)
        except Exception:
            pass

    async def komut_isle(self, mesaj: dict):
        komut_id = mesaj.get("komutId")
        komut = mesaj.get("komut", {})
        komut_turu = komut.get("kind")
        kabul = True
        neden = None

        if komut_turu == "head.target":
            yeni_yaw = float(komut.get("yawDeg", 0))
            self.hedef_yaw = max(-85.0, min(85.0, yeni_yaw))
            if self.ros_node is not None:
                try:
                    msg_f = RosFloat32()
                    msg_f.data = float(self.hedef_yaw)
                    self.pub_head_cmd_pos.publish(msg_f)
                except Exception:
                    pass
        elif komut_turu == "head.center":
            self.hedef_yaw = 0.0
            if self.ros_node is not None:
                try:
                    msg_f = RosFloat32()
                    msg_f.data = 0.0
                    self.pub_head_cmd_pos.publish(msg_f)
                except Exception:
                    pass
        elif komut_turu == "estop":
            self.estop = bool(komut.get("engaged", False))
            if self.ros_node is not None:
                try:
                    msg_b = RosBool()
                    msg_b.data = self.estop
                    self.pub_safety_estop.publish(msg_b)
                except Exception:
                    pass

        if komut_id and self.ws:
            try:
                await self.ws.send(json.dumps({"kind": "cihaz.onay", "komutId": komut_id, "kabul": kabul, "neden": neden}))
            except Exception:
                pass

    async def telemetri_dongusu(self):
        """Fastify ağ geçidine 10 Hz telemetri basar."""
        if not self.kabul_edildi:
            return
        await self.kabul_edildi.wait()
        while self.calisiyor and self.ws:
            t_obj = self.get_normalized_telemetry()
            clean_faces = []
            for fc in self.faces_list:
                clean_faces.append({
                    "name": fc["name"] if fc.get("is_known") else "Misafir",
                    "confidence": fc.get("confidence", 0.0),
                    "box": fc.get("box", [0.2, 0.2, 0.3, 0.4]),
                    "distanceM": fc.get("distance_m", 1.5),
                })

            telemetri = {
                "kind": "cihaz.telemetri",
                "payload": {
                    "t": int(time.time() * 1000),
                    "source": "robot",
                    "connected": True,
                    "head": {
                        "desiredYawDeg": round(self.hedef_yaw, 1),
                        "actualYawDeg": round(self.gercek_yaw, 1),
                        "encoderOk": bool(self.encoder_ok),
                    },
                    "audio": {
                        "doaDeg": round(self.doa_deg, 1) if self.vad else None,
                        "confidence": round(self.doa_confidence, 2),
                        "vad": bool(self.vad),
                    },
                    "gaze": {
                        "attentionOwner": self.attention_owner,
                        "state": self.gaze_state,
                        "visualValid": self.visual_valid,
                    },
                    "faces": clean_faces,
                    "safety": {
                        "eStop": bool(self.estop),
                        "watchdogOk": bool(self.watchdog_ok),
                    },
                    "speech": {
                        "lastTranscript": self.son_konusma or None,
                        "lastSpeaker": self.aktif_muhatap if self.kimlik_dogrulandi else "Misafir",
                        "emotion": self.robot_duygu,
                        "state": self.robot_state.lower(),
                    },
                },
            }
            try:
                await self.ws.send(json.dumps(telemetri))
            except Exception:
                break
            await asyncio.sleep(0.1)

    async def ayar_senkronizasyon_dongusu(self):
        if not self.kabul_edildi or not self.site_url:
            return
        await self.kabul_edildi.wait()
        while self.calisiyor:
            try:
                await self._sync_settings_from_web()
            except Exception:
                pass
            await asyncio.sleep(2.0)

    async def _sync_settings_from_web(self):
        url = f"{self.site_url}/api/cihaz/ayarlar?serial={self.serial}"
        loop = asyncio.get_running_loop()

        def _fetch():
            req = urllib.request.Request(url, headers={"User-Agent": "AstroWebAgent/1.0"})
            with urllib.request.urlopen(req, timeout=3) as resp:
                return json.loads(resp.read().decode("utf-8"))

        try:
            data = await loop.run_in_executor(None, _fetch)
        except Exception:
            return

        if not data.get("ok"):
            return

        ayarlar = data.get("ayarlar", {})
        guncelleme_zamani = ayarlar.get("updatedAt", "")
        if guncelleme_zamani != self.son_ayar_guncelleme:
            self.son_ayar_guncelleme = guncelleme_zamani
            persona = ayarlar.get("persona", "playful")
            voice = ayarlar.get("ttsVoice", "echo")
            prompt = ayarlar.get("llmPrompt", "")

            if self.ros_node is not None and self.pub_config_update is not None:
                try:
                    cfg_msg = RosString()
                    cfg_msg.data = json.dumps({
                        "persona": persona,
                        "voice": voice,
                        "prompt": prompt,
                        "updatedAt": guncelleme_zamani,
                    })
                    self.pub_config_update.publish(cfg_msg)
                except Exception:
                    pass


# --- TEKİL MODERN DASHBOARD HTML VE CSS ---

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="tr">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>ASTRO V1 · Canlı Bilinç ve Telemetri Konsolu</title>
  <style>
    :root {
      --bg-dark: #0a0d14;
      --panel-bg: rgba(18, 24, 38, 0.75);
      --border: rgba(255, 255, 255, 0.08);
      --cyan: #00f0ff;
      --green: #10b981;
      --amber: #f59e0b;
      --red: #ef4444;
      --purple: #a855f7;
      --text: #f1f5f9;
      --muted: #94a3b8;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      background: var(--bg-dark);
      color: var(--text);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, monospace;
      padding: 1rem;
      min-height: 100vh;
    }
    .header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding-bottom: 1rem;
      border-bottom: 1px solid var(--border);
      margin-bottom: 1rem;
    }
    .title-box { display: flex; align-items: center; gap: 0.75rem; }
    .logo-badge {
      background: linear-gradient(135deg, var(--cyan), #3b82f6);
      color: #000;
      font-weight: 900;
      padding: 0.25rem 0.6rem;
      border-radius: 4px;
      font-size: 0.85rem;
      letter-spacing: 1px;
    }
    .title { font-size: 1.15rem; font-weight: 700; letter-spacing: 0.5px; }
    .header-pills { display: flex; gap: 0.6rem; align-items: center; }
    .pill {
      display: inline-flex;
      align-items: center;
      gap: 0.4rem;
      padding: 0.35rem 0.75rem;
      border-radius: 9999px;
      font-size: 0.75rem;
      font-weight: 600;
      border: 1px solid var(--border);
      background: rgba(255, 255, 255, 0.04);
      text-transform: uppercase;
    }
    .pill--green { color: var(--green); border-color: rgba(16, 185, 129, 0.3); }
    .pill--amber { color: var(--amber); border-color: rgba(245, 158, 11, 0.3); }
    .pill--purple { color: var(--purple); border-color: rgba(168, 85, 247, 0.3); }
    .pill--cyan { color: var(--cyan); border-color: rgba(0, 240, 255, 0.3); }
    .dot { width: 8px; height: 8px; border-radius: 50%; background: currentColor; }
    .pulse { animation: pulse 1.5s infinite; }
    @keyframes pulse { 0%, 100% { opacity: 1; transform: scale(1); } 50% { opacity: 0.4; transform: scale(1.2); } }

    .main-layout {
      display: grid;
      grid-template-columns: 1.25fr 1fr;
      gap: 1.2rem;
      margin-bottom: 1rem;
    }
    @media (max-width: 1080px) { .main-layout { grid-template-columns: 1fr; } }

    .panel {
      background: var(--panel-bg);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 1rem;
      position: relative;
      backdrop-filter: blur(10px);
    }
    .panel__title {
      font-size: 0.75rem;
      text-transform: uppercase;
      letter-spacing: 1px;
      color: var(--muted);
      margin-bottom: 0.85rem;
      display: flex;
      justify-content: space-between;
    }

    /* Video Viewport & Overlays */
    .video-container {
      position: relative;
      width: 100%;
      aspect-ratio: 16 / 9;
      background: #000;
      border-radius: 6px;
      overflow: hidden;
      border: 1px solid rgba(255,255,255,0.1);
    }
    .video-container img { width: 100%; height: 100%; object-fit: cover; display: block; }
    .overlay-svg {
      position: absolute;
      top: 0; left: 0; width: 100%; height: 100%;
      pointer-events: none;
    }
    .video-hud {
      position: absolute;
      bottom: 8px;
      left: 8px;
      right: 8px;
      display: flex;
      justify-content: space-between;
      font-size: 0.7rem;
      background: rgba(0, 0, 0, 0.65);
      padding: 0.3rem 0.6rem;
      border-radius: 4px;
      color: var(--cyan);
    }

    /* Readouts */
    .stat-row { display: flex; justify-content: space-between; margin-bottom: 0.6rem; font-size: 0.85rem; }
    .stat-label { color: var(--muted); }
    .stat-val { font-weight: 600; font-family: monospace; }

    /* Meter Bars */
    .meter {
      height: 6px;
      width: 100%;
      background: rgba(255,255,255,0.06);
      border-radius: 3px;
      margin: 0.35rem 0 0.75rem;
      overflow: hidden;
    }
    .meter-fill { height: 100%; width: 0%; transition: width 0.15s ease; border-radius: 3px; }
    .fill--cyan { background: var(--cyan); }
    .fill--green { background: var(--green); }
    .fill--amber { background: var(--amber); }

    .bubble {
      padding: 0.75rem;
      border-radius: 6px;
      margin-bottom: 0.6rem;
      font-size: 0.85rem;
      line-height: 1.4;
    }
    .bubble--user { background: rgba(59, 130, 246, 0.1); border-left: 3px solid #3b82f6; }
    .bubble--astro { background: rgba(16, 185, 129, 0.1); border-left: 3px solid var(--green); }
    .bubble-author { font-size: 0.7rem; color: var(--muted); text-transform: uppercase; margin-bottom: 0.2rem; }

    .terminal {
      background: rgba(0,0,0,0.5);
      border: 1px solid var(--border);
      border-radius: 6px;
      height: 160px;
      overflow-y: auto;
      padding: 0.6rem;
      font-size: 0.75rem;
      font-family: monospace;
    }
    .terminal-entry { margin-bottom: 0.3rem; display: flex; gap: 0.5rem; }
    .entry-time { color: var(--muted); }
    .entry-tag { font-weight: bold; }
    .tag-WAKE { color: var(--amber); }
    .tag-VISION { color: var(--cyan); }
    .tag-STT { color: #38bdf8; }
    .tag-TTS { color: var(--green); }
    .tag-SAFETY { color: var(--red); }
    .tag-AUDIO { color: var(--purple); }
    .tag-AI { color: #818cf8; }
    .tag-SYSTEM { color: var(--muted); }

    .btn {
      padding: 0.4rem 0.8rem;
      background: rgba(255, 255, 255, 0.08);
      border: 1px solid var(--border);
      color: var(--text);
      border-radius: 4px;
      font-size: 0.75rem;
      cursor: pointer;
      font-weight: 600;
    }
    .btn:hover { background: rgba(255,255,255,0.15); }
    .btn--red { background: rgba(239, 68, 68, 0.2); border-color: var(--red); color: #fca5a5; }
  </style>
</head>
<body>
  <div class="header">
    <div class="title-box">
      <span class="logo-badge">ASTRO V1</span>
      <h1 class="title">Bilinç & Telemetri Kontrol Paneli</h1>
    </div>
    <div class="header-pills">
      <span class="pill pill--cyan" id="pill-mode"><span class="dot"></span><span>MODE: <strong id="mode-name">4O</strong></span></span>
      <span class="pill pill--purple" id="pill-model"><span class="dot"></span><span id="model-name">gpt-4o-mini</span></span>
      <span class="pill pill--green" id="pill-state"><span class="dot pulse"></span><span id="state-text">IDLE</span></span>
      <button class="btn btn--red" id="btn-estop" onclick="toggleEstop()">ACİL DURDURMA</button>
    </div>
  </div>

  <div class="main-layout">
    <!-- SOL SÜTUN: 16:9 Canlı Kamera & Diyalog Paneli -->
    <div class="col-left">
      <!-- 1. Canlı Kamera & Bounding Box HUD -->
      <div class="panel">
        <div class="panel__title">
          <span>👁️ Canlı Kamera & Görsel Takip (OAK-D Lite)</span>
          <span id="cam-fps" style="color:var(--cyan)">0.0 FPS</span>
        </div>
        <div class="video-container">
          <img id="mjpg-stream" src="/camera/stream.mjpg" alt="Astro Kamera Akışı" onerror="retryStream()" />
          <svg class="overlay-svg" id="box-overlay" viewBox="0 0 1000 1000" preserveAspectRatio="none"></svg>
          <div class="video-hud">
            <span id="hud-person">Kişi: 0 · Görsel Varlık: HAYIR</span>
            <span id="hud-gaze">Gaze: IDLE</span>
          </div>
        </div>
      </div>

      <!-- 2. Diyalog & Pipeline Gecikme Metrikleri -->
      <div class="panel" style="margin-top: 1rem;">
        <div class="panel__title">
          <span>💬 Diyalog & End-to-End Pipeline Metrikleri</span>
          <span id="lat-metrics" style="color:var(--cyan);font-family:monospace">E2E: 0ms</span>
        </div>
        <div class="bubble bubble--user">
          <div class="bubble-author">Kullanıcı (STT)</div>
          <div id="txt-user">Henüz konuşma algılanmadı...</div>
        </div>
        <div class="bubble bubble--astro">
          <div class="bubble-author">Astro (TTS)</div>
          <div id="txt-astro">Seni dinliyorum...</div>
        </div>
        <div style="background: rgba(0,0,0,0.3); padding: 0.5rem 0.75rem; border-radius: 4px; border: 1px solid var(--border); font-size: 0.75rem;">
          <div style="display: flex; justify-content: space-between; font-family: monospace;">
            <span>MODEL: <strong id="lat-model" style="color:var(--purple)">gpt-4o-mini</strong></span>
            <span>TTFT: <strong id="lat-ttft">0ms</strong></span>
            <span>TTFA: <strong id="lat-ttfa">0ms</strong></span>
            <span>E2E: <strong id="lat-e2e" style="color:var(--cyan)">0ms</strong></span>
          </div>
        </div>
      </div>
    </div>

    <!-- SAĞ SÜTUN: Bilişsel Kartlar & Event Stream -->
    <div class="col-right">
      <!-- 1. Biyometrik Kimlik & Oturum -->
      <div class="panel">
        <div class="panel__title">👤 Biyometrik Kimlik & Oturum</div>
        <div class="stat-row">
          <span class="stat-label">Muhatap İsmi</span>
          <span class="stat-val" id="id-name" style="color:var(--cyan);font-weight:700;">Misafir</span>
        </div>
        <div class="stat-row">
          <span class="stat-label">Doğrulama Durumu</span>
          <span class="stat-val" id="id-verified" style="color:var(--amber)">Doğrulanmamış</span>
        </div>
        <div class="stat-row">
          <span class="stat-label">Kimlik Kaynağı</span>
          <span class="stat-val" id="id-source">—</span>
        </div>
        <div class="stat-row">
          <span class="stat-label">Tanınma Skoru</span>
          <span class="stat-val" id="id-conf">0%</span>
        </div>
        <div class="meter"><div class="meter-fill fill--cyan" id="meter-id"></div></div>
      </div>

      <!-- 2. Fiziksel Robot Durumu -->
      <div class="panel" style="margin-top: 1rem;">
        <div class="panel__title">🤖 Fiziksel Robot Durumu</div>
        <div class="stat-row">
          <span class="stat-label">Kafa Açısı (Hedef / Gerçek)</span>
          <span class="stat-val" id="head-yaw">0.0° / 0.0°</span>
        </div>
        <div class="stat-row">
          <span class="stat-label">Encoder & Watchdog</span>
          <span class="stat-val" id="stat-sensors" style="color:var(--green)">SAĞLAM</span>
        </div>
        <div class="stat-row">
          <span class="stat-label">Uyku Modu</span>
          <span class="stat-val" id="stat-sleep">UYANIK</span>
        </div>
        <div style="margin-top: 0.5rem; display: flex; gap: 0.5rem;">
          <button class="btn" onclick="setHead(0)">Merkez (0°)</button>
          <button class="btn" onclick="setHead(30)">Sol (+30°)</button>
          <button class="btn" onclick="setHead(-30)">Sağ (-30°)</button>
        </div>
      </div>

      <!-- 3. Akustik & Barge-In Telemetrisi -->
      <div class="panel" style="margin-top: 1rem;">
        <div class="panel__title">🎙️ Akustik & Barge-In Telemetrisi</div>
        <div class="stat-row">
          <span class="stat-label">Mikrofon Seviyesi (RMS)</span>
          <span class="stat-val" id="aud-rms">0.000</span>
        </div>
        <div class="meter"><div class="meter-fill fill--green" id="meter-rms"></div></div>
        <div class="stat-row">
          <span class="stat-label">VAD (Konuşma Algılama)</span>
          <span class="stat-val" id="aud-vad" style="color:var(--muted)">SESSİZLİK</span>
        </div>
        <div class="stat-row">
          <span class="stat-label">Playback Reference (Ch5 AEC)</span>
          <span class="stat-val" id="aud-playback">BOŞTA</span>
        </div>
        <div class="stat-row">
          <span class="stat-label">Self-Voice Score (Kendi Sesi)</span>
          <span class="stat-val" id="aud-self-voice">0.00</span>
        </div>
        <div class="meter"><div class="meter-fill fill--amber" id="meter-self"></div></div>
        <div class="stat-row">
          <span class="stat-label">Barge-in Durumu</span>
          <span class="stat-val" id="aud-bargein" style="color:var(--green)">NORMAL</span>
        </div>
        <div class="stat-row">
          <span class="stat-label">Ses Açısı (DoA Azimut)</span>
          <span class="stat-val" id="aud-doa">—</span>
        </div>
      </div>

      <!-- 4. Canlı Bilişsel Olay Akışı -->
      <div class="panel" style="margin-top: 1rem;">
        <div class="panel__title">⚡ Canlı Bilişsel Olay Akışı (Event Stream)</div>
        <div class="terminal" id="terminal"></div>
      </div>
    </div>
  </div>

  <script>
    let streamImg = document.getElementById("mjpg-stream");
    let svgOverlay = document.getElementById("box-overlay");
    let termBox = document.getElementById("terminal");
    let lastEventId = 0;

    function retryStream() {
      setTimeout(() => {
        streamImg.src = "/camera/stream.mjpg?t=" + Date.now();
      }, 1000);
    }

    async function pollTelemetry() {
      try {
        let resp = await fetch("/api/telemetry");
        let d = await resp.json();
        updateUI(d);
      } catch (err) {}
    }
    setInterval(pollTelemetry, 100);

    function updateUI(d) {
      // Top bar
      if (document.getElementById("mode-name")) {
        document.getElementById("mode-name").innerText = d.ai_conversation.mode || "4O";
      }
      document.getElementById("model-name").innerText = d.ai_conversation.current_model || "gpt-4o-mini";
      document.getElementById("state-text").innerText = d.robot_state;
      let pState = document.getElementById("pill-state");
      pState.className = "pill " + (d.robot_state === "SPEAKING" ? "pill--green" : (d.robot_state === "LISTENING" ? "pill--amber" : "pill--cyan"));

      // Video & Tracking
      document.getElementById("cam-fps").innerText = d.visual_tracking.camera_fps.toFixed(1) + " FPS";
      document.getElementById("hud-person").innerText = "Kişi: " + d.visual_tracking.person_count + " · Görsel Varlık: " + (d.visual_tracking.visual_presence ? "EVET" : "HAYIR");
      document.getElementById("hud-gaze").innerText = "Gaze: " + d.visual_tracking.gaze_state + " (" + d.visual_tracking.attention_owner + ")";

      // SVG Bounding Boxes
      renderBoxes(d.visual_tracking.faces || []);

      // Identity
      document.getElementById("id-name").innerText = d.identity.name;
      let idVer = document.getElementById("id-verified");
      idVer.innerText = d.identity.verified ? "Doğrulandı" : "Doğrulanmamış (Misafir)";
      idVer.style.color = d.identity.verified ? "var(--green)" : "var(--amber)";
      document.getElementById("id-source").innerText = d.identity.identity_source;
      document.getElementById("id-conf").innerText = Math.round(d.identity.confidence * 100) + "%";
      document.getElementById("meter-id").style.width = Math.min(100, Math.round(d.identity.confidence * 100)) + "%";

      // Head & Robot
      document.getElementById("head-yaw").innerText = d.head.desiredYawDeg.toFixed(1) + "° / " + d.head.actualYawDeg.toFixed(1) + "°";
      document.getElementById("stat-sensors").innerText = d.head.encoderOk ? "SAĞLAM" : "HATA";
      document.getElementById("stat-sensors").style.color = d.head.encoderOk ? "var(--green)" : "var(--red)";
      document.getElementById("stat-sleep").innerText = d.is_sleeping ? "UYKU" : "UYANIK";

      // Audio
      document.getElementById("aud-rms").innerText = d.audio_speech.mic_rms.toFixed(4);
      let rmsPct = Math.min(100, Math.round(d.audio_speech.mic_rms * 800));
      document.getElementById("meter-rms").style.width = rmsPct + "%";
      let vadEl = document.getElementById("aud-vad");
      vadEl.innerText = d.audio_speech.vad ? "🗣️ KONUŞMA VAR" : "🔇 SESSİZLİK";
      vadEl.style.color = d.audio_speech.vad ? "var(--cyan)" : "var(--muted)";
      document.getElementById("aud-self-voice").innerText = d.audio_speech.self_voice_score.toFixed(2);
      document.getElementById("meter-self").style.width = Math.round(d.audio_speech.self_voice_score * 100) + "%";
      document.getElementById("aud-playback").innerText = d.audio_speech.playback_active ? "ÇALIYOR" : "BOŞTA";
      document.getElementById("aud-playback").style.color = d.audio_speech.playback_active ? "var(--green)" : "var(--muted)";
      let bEl = document.getElementById("aud-bargein");
      bEl.innerText = d.audio_speech.barge_in_active ? "⚡ PLAYBACK KESİLDİ (BARGE-IN)" : "NORMAL";
      bEl.style.color = d.audio_speech.barge_in_active ? "var(--red)" : "var(--green)";
      document.getElementById("aud-doa").innerText = d.audio_speech.doa_deg !== null ? d.audio_speech.doa_deg + "° (Güven: " + d.audio_speech.doa_confidence + ")" : "—";

      // Dialogue
      if (d.ai_conversation.last_user_utterance) {
        document.getElementById("txt-user").innerText = "“" + d.ai_conversation.last_user_utterance + "”";
      }
      if (d.ai_conversation.last_assistant_response) {
        document.getElementById("txt-astro").innerText = "“" + d.ai_conversation.last_assistant_response + "”";
      }
      document.getElementById("lat-metrics").innerText = "E2E: " + Math.round(d.ai_conversation.e2e_playback_ms) + "ms";
      if (document.getElementById("lat-model")) {
        document.getElementById("lat-model").innerText = d.ai_conversation.current_model || "gpt-4o-mini";
        document.getElementById("lat-ttft").innerText = Math.round(d.ai_conversation.llm_ttft_ms) + "ms";
        document.getElementById("lat-ttfa").innerText = Math.round(d.ai_conversation.tts_ttfa_ms) + "ms";
        document.getElementById("lat-e2e").innerText = Math.round(d.ai_conversation.e2e_playback_ms) + "ms";
      }

      // Events
      if (d.events) {
        renderEvents(d.events);
      }
    }

    function renderBoxes(faces) {
      let svgHtml = "";
      for (let f of faces) {
        let b = f.box; // [x, y, w, h] normalized 0..1
        let x = b[0] * 1000;
        let y = b[1] * 1000;
        let w = b[2] * 1000;
        let h = b[3] * 1000;
        let color = f.is_known ? "#10b981" : "#00f0ff";
        let label = f.name + " (" + Math.round(f.confidence * 100) + "%) · " + (f.distance_m || 1.5) + "m";

        svgHtml += `<rect x="${x}" y="${y}" width="${w}" height="${h}" fill="none" stroke="${color}" stroke-width="3" rx="8" />`;
        svgHtml += `<rect x="${x}" y="${Math.max(0, y - 30)}" width="${label.length * 14 + 16}" height="28" fill="rgba(0,0,0,0.7)" rx="4" />`;
        svgHtml += `<text x="${x + 8}" y="${Math.max(20, y - 10)}" fill="${color}" font-size="18" font-family="monospace" font-weight="bold">${label}</text>`;
      }
      svgOverlay.innerHTML = svgHtml;
    }

    function renderEvents(evts) {
      let html = "";
      for (let e of evts) {
        html += `<div class="terminal-entry"><span class="entry-time">[${e.time}]</span> <span class="entry-tag tag-${e.category}">[${e.category}]</span> <span>${e.message}</span></div>`;
      }
      termBox.innerHTML = html;
      termBox.scrollTop = termBox.scrollHeight;
    }

    async function toggleEstop() {
      await fetch("/api/estop", { method: "POST" });
    }

    async function setHead(deg) {
      await fetch("/api/head", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ yaw_deg: deg })
      });
    }
  </script>
</body>
</html>
"""


def main():
    parser = argparse.ArgumentParser(description="ASTRO V1 Robot Web Gateway Client & Consciousness Dashboard")
    parser.add_argument("--gateway", help="Gateway URL (ws://...)")
    parser.add_argument("--site", default="http://127.0.0.1:3000", help="Web Panel URL (http://...)")
    parser.add_argument("--serial", default="ASTRO-V1-000123", help="Robot seri numarası")
    parser.add_argument("--pair", help="Panelden alınan eşleştirme kodu")
    parser.add_argument("--token", help="Doğrudan kalıcı jeton")
    parser.add_argument("--dashboard-port", type=int, default=8080, help="Canlı telemetri dashboard portu (Varsayılan: 8080)")

    args = parser.parse_args()

    kayitli = jeton_yukle()
    token = args.token or kayitli.get("token")
    gecit_url = args.gateway or kayitli.get("gecitUrl") or "ws://127.0.0.1:8420"
    site_url = args.site or "http://127.0.0.1:3000"

    if args.pair:
        eslesme = cihaz_eslestir(site_url, args.serial, args.pair)
        token = eslesme.get("token")
        gecit_url = eslesme.get("gecitUrl", args.gateway)
        jeton_kaydet({"token": token, "gecitUrl": gecit_url, "serial": args.serial})

    ajan = AstroRobotAjan(
        token=token,
        gecit_url=gecit_url,
        serial=args.serial,
        site_url=site_url,
        dashboard_port=args.dashboard_port,
    )

    try:
        asyncio.run(ajan.calistir())
    except KeyboardInterrupt:
        ajan.calisiyor = False
        print("\n🛑 Robot ajanı durduruldu.")


if __name__ == "__main__":
    main()
