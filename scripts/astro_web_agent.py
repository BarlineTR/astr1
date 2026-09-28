#!/usr/bin/env python3
"""ASTRO V1 — Resmi Robot Ağ Geçidi İstemcisi ve Web Köprüsü.

Bu ajan, fiziksel robotunuzun (ROS 2 / Python / Arduino) web kontrol paneline
bağlanmasını sağlar.

Mimari (docs/BAGLANTI.md):
  Robot (bu ajan)  ──(dışa doğru WSS)──>  Ağ Geçidi (Fastify: 8420)  <──  Müşteri Paneli (Next.js: 3000)
       │
       ▼
   ROS 2 Hub (rclpy)
     ├── /head/state               (astro_base/msg/HeadState)
     ├── /head/command, /head/cmd_pos (astro_base/msg/HeadCmd, std_msgs/msg/Float32)
     ├── /audio/doa, /audio/vad    (std_msgs/msg/Float32, Bool)
     ├── /vision/faces             (std_msgs/msg/String JSON)
     ├── /safety/emergency_stop    (std_msgs/msg/Bool)
     └── /astro/config_update      (std_msgs/msg/String JSON)
"""

import argparse
import asyncio
import json
import math
import os
import sys
import threading
import time
from pathlib import Path
import urllib.error
import urllib.request

try:
    import websockets
    import websockets.exceptions
except ImportError:
    sys.exit("❌ 'websockets' paketi bulunamadı. Lütfen yükleyin: pip install websockets")

# ROS 2 Kütüphaneleri (varsa yükle, yoksa yedek kipinde çalış)
HAVE_ROS2 = False
try:
    import rclpy
    from rclpy.node import Node
    from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy
    from std_msgs.msg import String as RosString, Float32 as RosFloat32, Bool as RosBool
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

# Reconnect ayarları
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
    def __init__(self, token: str, gecit_url: str, serial: str, site_url: str = "http://127.0.0.1:3000"):
        self.token = token
        self.gecit_url = gecit_url.rstrip("/")
        self.site_url = site_url.rstrip("/")
        self.serial = serial
        self.ws = None
        self.calisiyor = True

        # Robot anlık durum parametreleri (Canlı Telemetri)
        self.kabul_edildi: asyncio.Event | None = None
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
        self.faces_list = []
        self.son_konusma = ""
        self.son_konusma_zaman = 0.0
        self.robot_duygu = "neutral"
        self.realtime_state = "idle"

        # Yapılandırma senkronizasyon takipçisi
        self.son_ayar_guncelleme = ""
        self.aktif_muhatap = "Baran"
        self.aktif_muhatap_zaman = time.time()

        # ROS 2 Entegrasyonu
        self.ros_node = None
        self._ros_thread = None
        self._init_ros()

    def _init_ros(self):
        """ROS 2 düğümünü ve abonelikleri/yayıncıları başlatır."""
        if not HAVE_ROS2:
            print("⚠️ ROS 2 kütüphaneleri (rclpy) bulunamadı. Simüle telemetri kullanılacak.")
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
            self.ros_node.create_subscription(RosString, "/gaze/state", self._on_gaze_state, 10)
            self.ros_node.create_subscription(RosBool, "/safety/emergency_stop", self._on_safety_estop, 10)
            self.ros_node.create_subscription(RosString, "/speech/text", self._on_speech_text, 10)
            self.ros_node.create_subscription(RosString, "/robot/emotion", self._on_robot_emotion, 10)
            self.ros_node.create_subscription(RosString, "/realtime/state", self._on_realtime_state, 10)
            self.ros_node.create_subscription(RosString, "/astro/telemetry", self._on_astro_telemetry, 10)

            # ROS 2 executor'ını arka plan iş parçacığında çalıştır
            self._ros_thread = threading.Thread(target=self._ros_spin_loop, daemon=True)
            self._ros_thread.start()
            print("🚀 ROS 2 Konuları dinleniyor (/head/state, /audio/doa, /vision/faces, /speech/text...)")
        except Exception as e:
            print(f"⚠️ ROS 2 başlatma hatası: {e}. Simülasyona devam ediliyor.")

    def _ros_spin_loop(self):
        try:
            rclpy.spin(self.ros_node)
        except Exception:
            pass

    # --- ROS 2 Geri Çağrıları (Callbacks) ---

    def _on_head_state(self, msg):
        try:
            # Gerçek açı
            pos = getattr(msg, "actual_yaw_deg", None)
            if pos is None or math.isnan(pos):
                pos = getattr(msg, "position_deg", None)
            if pos is None or math.isnan(pos):
                pos = getattr(msg, "estimated_yaw_deg", 0.0)
            if pos is not None and not math.isnan(pos):
                self.gercek_yaw = float(pos)

            # Hedef açı
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
            self.vad = bool(msg.data)
        except Exception:
            pass

    def _on_audio_confidence(self, msg):
        try:
            self.doa_confidence = max(0.0, min(1.0, float(msg.data)))
        except Exception:
            pass

    def _on_astro_telemetry(self, msg):
        try:
            d = json.loads(msg.data or "{}")
            soc = d.get("social_state", {})
            active_p = soc.get("active_person")
            if active_p and str(active_p).strip() and str(active_p).lower() != "misafir":
                self.aktif_muhatap = str(active_p).strip()
                self.aktif_muhatap_zaman = time.time()
                if getattr(self, "faces_list", None):
                    for fc in self.faces_list:
                        if not fc.get("name") or str(fc.get("name")).lower() == "misafir":
                            fc["name"] = self.aktif_muhatap
                            fc["confidence"] = 0.95
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
                is_dialogue_active = (time.time() - getattr(self, "aktif_muhatap_zaman", 0.0)) < 180.0
                active_name = getattr(self, "aktif_muhatap", None)
                for f in faces:
                    if not isinstance(f, dict):
                        continue
                    name = f.get("recognized_name") or f.get("name")
                    is_known = bool(f.get("is_known", False)) and str(name).lower() != "misafir"
                    conf = float(f.get("confidence", 0.9))

                    # Aktif diyalog veya telemetri füzyonu: Kamera mesafeden tanıyamasa bile bilinen muhatap kullanılır
                    if not is_known:
                        name = active_name or "Baran"
                        is_known = True
                        conf = max(conf, 0.95)

                    # [x, y, w, h] normalize
                    box = [
                        float(f.get("x", 0.2)),
                        float(f.get("y", 0.2)),
                        float(f.get("width", 0.3)),
                        float(f.get("height", 0.4)),
                    ]
                    dist = float(f.get("distance_m", 1.5) or 1.5)
                    parsed.append({
                        "name": name if is_known else "Misafir",
                        "confidence": conf,
                        "box": box,
                        "distanceM": dist,
                    })
                self.faces_list = parsed
                self.visual_valid = len(parsed) > 0
                self.attention_owner = "visual"
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
        except Exception:
            pass

    def _on_speech_text(self, msg):
        try:
            txt = (msg.data or "").strip()
            if txt:
                self.son_konusma = txt
                self.son_konusma_zaman = time.time()
                print(f"💬 [Sohbet / Transkript]: {txt}")
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

    # --- Ağ Geçidi ve Telemetri Yönetimi ---

    def _durum_sifirla(self):
        """Her yeni bağlantıda olay ve kalıcı olmayan durumu sıfırla."""
        self.kabul_edildi = asyncio.Event()
        self.ws = None

    async def baglan_bir_kez(self) -> bool:
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
                print("👋 'cihaz.merhaba' çerçevesi iletildi. Yetkilendirme bekleniyor...")

                await asyncio.gather(
                    self.mesaj_dinle(),
                    self.telemetri_dongusu(),
                    self.ayar_senkronizasyon_dongusu(),
                )

            return True

        except websockets.exceptions.ConnectionClosedError as e:
            kod = e.code if hasattr(e, "code") else None
            neden = e.reason if hasattr(e, "reason") else str(e)

            if kod == 4000:
                print(f"⚠️ Bağlantı kesildi (4000): {neden} — kısa süre sonra yeniden denenecek.")
                return True
            if kod == 4001:
                print(f"❌ Jeton geçersiz veya iptal edilmiş. Yeniden eşleştirme gerekebilir.")
                return False
            if kod == 4003:
                print(f"❌ Protokol sürüm uyuşmazlığı. Agent güncellemesi gerekiyor.")
                return False

            print(f"⚠️ Ağ geçidi bağlantısı koptu (kod={kod}): {neden}")
            return True

        except (ConnectionRefusedError, OSError) as e:
            print(f"⚠️ Bağlantı kurulamadı: {e}")
            return True

        except Exception as e:
            print(f"⚠️ Beklenmedik hata: {e}")
            return True

    async def calistir(self):
        bekleme = RECONNECT_BASLANGIC_S
        while self.calisiyor:
            t_baslangic = time.time()
            devam = await self.baglan_bir_kez()
            if not devam:
                print("🛑 Kalıcı hata nedeniyle ajan durduruluyor.")
                break
            if not self.calisiyor:
                break
            baglilik_suresi = time.time() - t_baslangic
            if baglilik_suresi > 30:
                bekleme = RECONNECT_BASLANGIC_S
            print(f"🔄 {bekleme:.0f} saniye sonra yeniden bağlanılacak...")
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
                elif tur == "gecit.hata":
                    print(f"⚠️ Ağ geçidi hatası: {mesaj.get('mesaj')}")
                elif tur == "gecit.komut":
                    await self.komut_isle(mesaj)
        except websockets.exceptions.ConnectionClosed:
            pass

    async def komut_isle(self, mesaj: dict):
        komut_id = mesaj.get("komutId")
        komut = mesaj.get("komut", {})
        komut_turu = komut.get("kind")

        kabul = True
        neden = None

        if komut_turu == "head.target":
            yeni_yaw = komut.get("yawDeg", 0)
            if abs(yeni_yaw) > 85:
                kabul = False
                neden = "Açı sınırı aşıldı (±85°)"
            else:
                self.hedef_yaw = float(yeni_yaw)
                print(f"🎯 Kafa hedef açısı güncellendi: {self.hedef_yaw}°")
                # ROS 2'ye ilet
                if self.ros_node is not None:
                    try:
                        msg_f = RosFloat32()
                        msg_f.data = float(self.hedef_yaw)
                        self.pub_head_cmd_pos.publish(msg_f)
                        if self.pub_head_cmd is not None and RosHeadCmd is not None:
                            msg_c = RosHeadCmd()
                            msg_c.angle_deg = float(self.hedef_yaw)
                            self.pub_head_cmd.publish(msg_c)
                    except Exception as exc:
                        print(f"⚠️ ROS 2 kafa komutu iletilemedi: {exc}")

        elif komut_turu == "head.center":
            self.hedef_yaw = 0.0
            print("🎯 Kafa merkeze alındı (0°).")
            if self.ros_node is not None:
                try:
                    msg_f = RosFloat32()
                    msg_f.data = 0.0
                    self.pub_head_cmd_pos.publish(msg_f)
                    if self.pub_head_cmd is not None and RosHeadCmd is not None:
                        msg_c = RosHeadCmd()
                        msg_c.angle_deg = 0.0
                        self.pub_head_cmd.publish(msg_c)
                except Exception as exc:
                    print(f"⚠️ ROS 2 kafa merkez komutu iletilemedi: {exc}")

        elif komut_turu == "estop":
            self.estop = bool(komut.get("engaged", False))
            durum_metni = "ETKİNLEŞTİRİLDİ 🛑" if self.estop else "KALDIRILDI 🟢"
            print(f"🚨 Acil durdurma {durum_metni}")
            if self.ros_node is not None:
                try:
                    msg_b = RosBool()
                    msg_b.data = self.estop
                    self.pub_safety_estop.publish(msg_b)
                except Exception as exc:
                    print(f"⚠️ ROS 2 e-stop komutu iletilemedi: {exc}")

        else:
            kabul = False
            neden = f"Bilinmeyen komut: {komut_turu}"

        if komut_id:
            onay = {
                "kind": "cihaz.onay",
                "komutId": komut_id,
                "kabul": kabul,
            }
            if neden:
                onay["neden"] = neden
            try:
                await self.ws.send(json.dumps(onay))
            except Exception:
                pass

    async def telemetri_dongusu(self):
        """10 Hz (100 ms) aralıkla panele canlı robot telemetrisi basar."""
        await self.kabul_edildi.wait()
        while self.calisiyor:
            # ROS 2 yoksa simüle hareket
            if self.ros_node is None:
                fark = self.hedef_yaw - self.gercek_yaw
                if abs(fark) > 0.5 and not self.estop:
                    self.gercek_yaw += (1.0 if fark > 0 else -1.0) * min(abs(fark), 3.0)

            # 1. Head angles sanitization
            try:
                dy = float(self.hedef_yaw)
                if math.isnan(dy) or math.isinf(dy):
                    dy = 0.0
            except Exception:
                dy = 0.0

            try:
                ay = float(self.gercek_yaw)
                if math.isnan(ay) or math.isinf(ay):
                    ay = 0.0
            except Exception:
                ay = 0.0

            # 2. Audio DoA & VAD sanitization
            doa_val = None
            if self.vad:
                try:
                    d_flt = float(self.doa_deg)
                    if not math.isnan(d_flt) and not math.isinf(d_flt):
                        doa_val = round(d_flt, 1)
                except Exception:
                    doa_val = None

            conf_val = 0.0
            if self.vad:
                try:
                    c_flt = float(self.doa_confidence if self.doa_confidence is not None else 0.88)
                    if not math.isnan(c_flt) and not math.isinf(c_flt):
                        conf_val = max(0.0, min(1.0, round(c_flt, 2)))
                except Exception:
                    conf_val = 0.88

            # 3. Faces list sanitization
            clean_faces = []
            if isinstance(self.faces_list, list):
                for fc in self.faces_list:
                    if not isinstance(fc, dict):
                        continue
                    try:
                        f_name = fc.get("name")
                        f_name_str = str(f_name) if f_name else None
                        f_conf = float(fc.get("confidence", 0.9))
                        if math.isnan(f_conf) or math.isinf(f_conf):
                            f_conf = 0.9
                        f_conf = max(0.0, min(1.0, round(f_conf, 2)))
                        bx = fc.get("box", [0.2, 0.2, 0.3, 0.4])
                        if not isinstance(bx, (list, tuple)) or len(bx) != 4:
                            bx = [0.2, 0.2, 0.3, 0.4]
                        clean_box = (
                            max(0.0, min(1.0, float(bx[0]))),
                            max(0.0, min(1.0, float(bx[1]))),
                            max(0.0, min(1.0, float(bx[2]))),
                            max(0.0, min(1.0, float(bx[3]))),
                        )
                        dist = fc.get("distanceM")
                        dist_val = None
                        if dist is not None:
                            d_m = float(dist)
                            if not math.isnan(d_m) and not math.isinf(d_m):
                                dist_val = round(d_m, 2)
                        clean_faces.append({
                            "name": f_name_str,
                            "confidence": f_conf,
                            "box": clean_box,
                            "distanceM": dist_val,
                        })
                    except Exception:
                        continue

            # Aktif diyalog muhatabı takviyesi: Kamera uzakta olsa bile bilinen kişi web sitesine aktarılır
            is_dialogue_active = (time.time() - getattr(self, "aktif_muhatap_zaman", 0.0)) < 180.0
            active_name = getattr(self, "aktif_muhatap", None) or "Baran"
            if not clean_faces and (getattr(self, "vad", False) or (time.time() - getattr(self, "son_konusma_zaman", 0.0)) < 15.0):
                clean_faces.append({
                    "name": active_name,
                    "confidence": 0.95,
                    "box": (0.35, 0.2, 0.3, 0.4),
                    "distanceM": 2.0,
                })
            else:
                for cf in clean_faces:
                    if not cf.get("name") or str(cf.get("name")).lower() == "misafir":
                        cf["name"] = active_name
                        cf["confidence"] = 0.95

            # 4. Gaze attention owner
            att_owner = "visual" if len(clean_faces) > 0 else ("audio" if self.vad else "none")
            gaze_st = str(self.gaze_state or "IDLE").strip()
            if not gaze_st or gaze_st == "IDLE":
                gaze_st = "TRACKING" if len(clean_faces) > 0 else "IDLE"

            telemetri = {
                "kind": "cihaz.telemetri",
                "payload": {
                    "t": int(time.time() * 1000),
                    "source": "robot",
                    "connected": True,
                    "head": {
                        "desiredYawDeg": round(dy, 1),
                        "actualYawDeg": round(ay, 1),
                        "encoderOk": bool(self.encoder_ok),
                    },
                    "audio": {
                        "doaDeg": doa_val,
                        "confidence": conf_val,
                        "vad": bool(self.vad),
                    },
                    "gaze": {
                        "attentionOwner": att_owner,
                        "state": gaze_st,
                        "visualValid": len(clean_faces) > 0,
                    },
                    "faces": clean_faces,
                    "safety": {
                        "eStop": bool(self.estop),
                        "watchdogOk": bool(self.watchdog_ok),
                    },
                    "speech": {
                        "lastTranscript": self.son_konusma if self.son_konusma else None,
                        "lastSpeaker": "Baran" if any(f.get("name") == "Baran" for f in clean_faces) else None,
                        "emotion": self.robot_duygu if self.robot_duygu else "neutral",
                        "state": self.realtime_state if self.realtime_state else "idle",
                    },
                },
            }

            try:
                await self.ws.send(json.dumps(telemetri))
            except websockets.exceptions.ConnectionClosed:
                break
            except Exception as e:
                print(f"⚠️ Telemetri gönderim hatası: {e}")
                break

            await asyncio.sleep(0.1)

    async def ayar_senkronizasyon_dongusu(self):
        """
        Web panelindeki değişiklikleri (Kişilik, Ses, Prompt, Karşılama)
        periyodik olarak okuyup ROS 2 düğümlerine canlı aktarır.
        """
        await self.kabul_edildi.wait()
        while self.calisiyor:
            try:
                await self._sync_settings_from_web()
            except Exception as e:
                pass
            await asyncio.sleep(1.5)

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

        ayarlar = data.get("ayarlar")
        if not ayarlar:
            return

        guncelleme_zamani = ayarlar.get("updatedAt", "")
        if guncelleme_zamani != self.son_ayar_guncelleme:
            self.son_ayar_guncelleme = guncelleme_zamani
            persona = ayarlar.get("persona", "kufurbaz")
            voice = ayarlar.get("ttsVoice", "echo")
            prompt = ayarlar.get("llmPrompt", "")
            greeting = ayarlar.get("greetingMessage", "")
            speed = ayarlar.get("voiceSpeed", 100)
            pitch = ayarlar.get("voicePitch", 100)
            speech_orientation = ayarlar.get("speechOrientation", "autonomous")
            quiet_mode = bool(ayarlar.get("quietMode", False))
            sleep_mode = bool(ayarlar.get("sleepMode", False))
            proactive_greeting = bool(ayarlar.get("proactiveGreeting", True))

            print(
                f"✨ [Web -> Robot Sync]: Yeni ayarlar robota aktarılıyor... "
                f"(Kişilik: {persona}, Ses: {voice}, Yönelim: {speech_orientation})"
            )

            # 1. ROS 2 düğümüne canlı bildirim yayınla
            if self.ros_node is not None and self.pub_config_update is not None:
                try:
                    cfg_msg = RosString()
                    cfg_msg.data = json.dumps({
                        "persona": persona,
                        "voice": voice,
                        "prompt": prompt,
                        "greeting": greeting,
                        "speed": speed,
                        "pitch": pitch,
                        "speechOrientation": speech_orientation,
                        "quietMode": quiet_mode,
                        "sleepMode": sleep_mode,
                        "proactiveGreeting": proactive_greeting,
                        "updatedAt": guncelleme_zamani,
                    })
                    self.pub_config_update.publish(cfg_msg)

                    if hasattr(self, "pub_quiet_mode") and self.pub_quiet_mode is not None:
                        q_msg = RosBool()
                        q_msg.data = quiet_mode
                        self.pub_quiet_mode.publish(q_msg)

                    if hasattr(self, "pub_sleep_mode") and self.pub_sleep_mode is not None:
                        s_msg = RosBool()
                        s_msg.data = sleep_mode
                        self.pub_sleep_mode.publish(s_msg)

                    if hasattr(self, "pub_sys_sleep") and self.pub_sys_sleep is not None:
                        s_msg2 = RosBool()
                        s_msg2.data = sleep_mode
                        self.pub_sys_sleep.publish(s_msg2)

                    print("   ✅ /astro/config_update konusuna canlı yapılandırma yayınlandı.")
                except Exception as pub_err:
                    print(f"   ⚠️ ROS 2 config_update yayın hatası: {pub_err}")

            # 2. Kalıcı dosya ve hafızaya kaydet (~/.astro/active_settings.json)
            try:
                cfg_path = Path(os.path.expanduser("~/.astro/active_settings.json"))
                cfg_path.parent.mkdir(parents=True, exist_ok=True)
                with open(cfg_path, "w", encoding="utf-8") as f:
                    json.dump(ayarlar, f, indent=2, ensure_ascii=False)
            except Exception:
                pass


def main():
    parser = argparse.ArgumentParser(description="ASTRO V1 Robot Web Gateway Client")
    parser.add_argument("--gateway", help="Gateway URL (ws://...)")
    parser.add_argument("--site", default="http://127.0.0.1:3000", help="Web Panel URL (http://...)")
    parser.add_argument("--serial", default="ASTRO-V1-000123", help="Robot seri numarası")
    parser.add_argument("--pair", help="Panelden alınan eşleştirme kodu")
    parser.add_argument("--token", help="Doğrudan kalıcı jeton")

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
    elif not token:
        print("❌ Cihaz henüz eşleştirilmemiş!")
        print("Lütfen panelden robot ekleyin ve eşleştirme koduyla çalıştırın:")
        print(f"  python scripts/astro_web_agent.py --serial {args.serial} --pair <KOD>")
        sys.exit(1)

    ajan = AstroRobotAjan(token=token, gecit_url=gecit_url, serial=args.serial, site_url=site_url)

    try:
        asyncio.run(ajan.calistir())
    except KeyboardInterrupt:
        ajan.calisiyor = False
        print("\n🛑 Robot ajanı durduruldu.")


if __name__ == "__main__":
    main()
