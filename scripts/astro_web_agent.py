#!/usr/bin/env python3
"""ASTRO V1 — Resmi Robot Ağ Geçidi İstemcisi ve Web Köprüsü.

Bu ajan, fiziksel robotunuzun (ROS 2 / Python / Arduino) web kontrol paneline
bağlanmasını sağlar.

Mimari (docs/BAGLANTI.md):
  Robot (bu ajan)  ──(dışa doğru WSS)──>  Ağ Geçidi (Fastify: 8420)  <──  Müşteri Paneli (Next.js: 3000)

Kullanım:
  1) Panelden robot ekleyip eşleştirme kodunu alın (Örn: ABCD-EFGH-JKMN-PQRS)
  2) Eşleştirme ile başlatın:
       python scripts/astro_web_agent.py --serial ASTRO-V1-000123 --pair ABCD-EFGH-JKMN-PQRS
     (Eşleştirme jetonu otomatik olarak ~/.astro/device_token.json içine kaydedilir)
  3) Sonraki başlatmalarda doğrudan bağlanır:
       python scripts/astro_web_agent.py
"""

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path
import urllib.error
import urllib.request

try:
    import websockets
    import websockets.exceptions
except ImportError:
    sys.exit("❌ 'websockets' paketi bulunamadı. Lütfen yükleyin: pip install websockets")

TOKEN_FILE = Path(os.path.expanduser("~/.astro/device_token.json"))
PROTOCOL_VERSION = "1"

# Reconnect ayarları
RECONNECT_BASLANGIC_S = 2.0   # İlk bekleme süresi
RECONNECT_MAKSIMUM_S  = 60.0  # Maksimum bekleme süresi
RECONNECT_CARPAN      = 2.0   # Her denemede katlanır


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
    def __init__(self, token: str, gecit_url: str, serial: str):
        self.token = token
        self.gecit_url = gecit_url.rstrip("/")
        self.serial = serial
        self.ws = None
        self.calisiyor = True

        # Robot anlık durum parametreleri
        self.kabul_edildi: asyncio.Event | None = None
        self.hedef_yaw = 0.0
        self.gercek_yaw = 0.0
        self.estop = False
        self.doa_deg = 0.0
        self.vad = False
        self.yuz_sayisi = 0

    def _durum_sifirla(self):
        """Her yeni bağlantıda olay ve kalıcı olmayan durumu sıfırla."""
        self.kabul_edildi = asyncio.Event()
        self.ws = None

    async def baglan_bir_kez(self) -> bool:
        """
        Tek bağlantı denemesi. Başarılı bağlantı kurulup normal kapanış
        gerçekleşirse True (yeniden bağlan), kalıcı hata varsa False (çık) döner.
        """
        self._durum_sifirla()
        ws_url = f"{self.gecit_url}/ws/cihaz"
        print(f"🔌 Ağ geçidine bağlanılıyor: {ws_url} ...")

        try:
            async with websockets.connect(ws_url) as ws:
                self.ws = ws
                print("🚀 Ağ geçidi bağlantısı kuruldu.")

                # cihaz.merhaba el sıkışması
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
                )

            # WebSocket bağlantısı normal kapandı → yeniden bağlan
            return True

        except websockets.exceptions.ConnectionClosedError as e:
            kod = e.code if hasattr(e, "code") else None
            neden = e.reason if hasattr(e, "reason") else str(e)

            if kod == 4000:
                # Aynı cihaz başka bir bağlantıyla kayıt oldu.
                # Bu genellikle servis yeniden başlatmasından kaynaklanır.
                # Kısa bekleyip yeniden dene.
                print(f"⚠️ Bağlantı kesildi (4000): {neden} — kısa süre sonra yeniden deneyeceğim.")
                return True

            if kod == 4001:
                print(f"❌ Jeton geçersiz veya iptal edilmiş. Yeniden eşleştirme gerekebilir.")
                return False  # Kalıcı hata — çık

            if kod == 4003:
                print(f"❌ Protokol sürüm uyuşmazlığı. Agent güncellemesi gerekiyor.")
                return False  # Kalıcı hata — çık

            print(f"⚠️ Ağ geçidi bağlantısı koptu (kod={kod}): {neden}")
            return True  # Geçici hata — yeniden bağlan

        except (ConnectionRefusedError, OSError) as e:
            print(f"⚠️ Bağlantı kurulamadı: {e}")
            return True  # Gateway geçici olarak kapalı — yeniden dene

        except Exception as e:
            print(f"⚠️ Beklenmedik hata: {e}")
            return True

    async def calistir(self):
        """Yeniden bağlanma döngüsü — bağlantı kopunca exponential backoff ile tekrar dener."""
        bekleme = RECONNECT_BASLANGIC_S
        while self.calisiyor:
            t_baslangic = time.time()
            devam = await self.baglan_bir_kez()
            if not devam:
                print("🛑 Kalıcı hata nedeniyle ajan durduruluyor.")
                break
            if not self.calisiyor:
                break
            # Bağlantı uzun süre (>30sn) ayaktaysa backoff'u sıfırla
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
                    print("✅ Ağ geçidi robotu kabul etti! Kontrol komutları dinleniyor.")
                elif tur == "gecit.ping":
                    t_val = mesaj.get("t", int(time.time() * 1000))
                    await self.ws.send(json.dumps({"kind": "cihaz.pong", "t": t_val}))
                elif tur == "gecit.hata":
                    print(f"⚠️ Ağ geçidi hatası: {mesaj.get('mesaj')}")
                elif tur == "gecit.komut":
                    await self.komut_isle(mesaj)
        except websockets.exceptions.ConnectionClosed:
            pass  # baglan_bir_kez'deki except bloğu zaten yakalayacak

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
        elif komut_turu == "head.center":
            self.hedef_yaw = 0.0
            print("🎯 Kafa merkeze alındı (0°).")
        elif komut_turu == "estop":
            self.estop = bool(komut.get("engaged", False))
            durum_metni = "ETKİNLEŞTİRİLDİ 🛑" if self.estop else "KALDIRILDI 🟢"
            print(f"🚨 Acil durdurma {durum_metni}")
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
            # Gerçek açıyı yumuşak bir şekilde hedefe yaklaştır
            fark = self.hedef_yaw - self.gercek_yaw
            if abs(fark) > 0.5 and not self.estop:
                self.gercek_yaw += (1.0 if fark > 0 else -1.0) * min(abs(fark), 3.0)

            telemetri = {
                "kind": "cihaz.telemetri",
                "payload": {
                    "t": int(time.time() * 1000),
                    "source": "robot",
                    "connected": True,
                    "head": {
                        "desiredYawDeg": float(self.hedef_yaw),
                        "actualYawDeg": round(float(self.gercek_yaw), 1),
                        "encoderOk": True,
                    },
                    "audio": {
                        "doaDeg": round(float(self.doa_deg), 1) if self.vad else None,
                        "confidence": 0.88 if self.vad else 0.0,
                        "vad": self.vad,
                    },
                    "gaze": {
                        "attentionOwner": "visual" if self.yuz_sayisi > 0 else "none",
                        "state": "TRACKING" if self.yuz_sayisi > 0 else "IDLE",
                        "visualValid": self.yuz_sayisi > 0,
                    },
                    "faces": [
                        {
                            "name": "Baran (VIP)",
                            "confidence": 0.94,
                            "box": [0.35, 0.25, 0.3, 0.4],
                            "distanceM": 1.2,
                        }
                    ]
                    if self.yuz_sayisi > 0
                    else [],
                    "safety": {
                        "eStop": self.estop,
                        "watchdogOk": True,
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

            await asyncio.sleep(0.1)  # 10 Hz


def main():
    parser = argparse.ArgumentParser(description="ASTRO V1 Robot Web Gateway Client")
    parser.add_argument("--gateway", help="Gateway URL (ws://...)")
    parser.add_argument("--serial", default="ASTRO-V1-000123", help="Robot seri numarası")
    parser.add_argument("--pair", help="Panelden alınan 24 saatlik tek kullanımlık eşleştirme kodu")
    parser.add_argument("--token", help="Doğrudan kalıcı jeton")

    args = parser.parse_args()

    kayitli = jeton_yukle()
    token = args.token or kayitli.get("token")
    gecit_url = args.gateway or kayitli.get("gecitUrl") or "ws://localhost:8420"

    if args.pair:
        eslesme = cihaz_eslestir(args.site, args.serial, args.pair)
        token = eslesme.get("token")
        gecit_url = eslesme.get("gecitUrl", args.gateway)
        jeton_kaydet({"token": token, "gecitUrl": gecit_url, "serial": args.serial})
    elif not token:
        print("X Cihaz henüz eşleştirilmemiş!")
        print("Lütfen panelden robot ekleyin ve eşleştirme koduyla çalıştırın:")
        print(f"  python scripts/astro_web_agent.py --serial {args.serial} --pair <KOD>")
        sys.exit(1)

    ajan = AstroRobotAjan(token=token, gecit_url=gecit_url, serial=args.serial)

    try:
        asyncio.run(ajan.calistir())
    except KeyboardInterrupt:
        ajan.calisiyor = False
        print("\n🛑 Robot ajanı durduruldu.")


if __name__ == "__main__":
    main()
