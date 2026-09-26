import type { Command, Telemetry } from "@astro/protocol";
import { PROTOCOL_VERSION } from "@astro/protocol";
import { gecitPanelCerceveSchema } from "@astro/protocol/wire";

/**
 * Tarayıcı ↔ ağ geçidi bağlantısı.
 *
 * Jetonu siteden alır, ağ geçidine bağlanır, gelen çerçeveleri sözleşmeye göre
 * doğrular. Sunucudan geleni de doğruluyoruz: ağ geçidi bizim olsa da araya
 * giren bir vekil ya da eski bir sürüm bozuk çerçeve gönderebilir ve
 * doğrulanmamış veriyi çizmek sessizce yanlış bir ekran demek.
 */

export type BaglantiDurumu =
  | "baglaniyor"
  | "yetkileniyor"
  | "bagli"
  | "robot-yok"
  | "kopuk"
  | "hata";

export interface CerceveKaydi {
  yon: "giden" | "gelen";
  tur: string;
  ozet: string;
  t: number;
}

export interface GecitOlaylari {
  durum(durum: BaglantiDurumu, ayrinti?: string): void;
  telemetri(t: Telemetry, gecikmeMs: number | null): void;
  cihazDurumu(bagli: boolean, sonGorulme: number | null, firmware: string | null): void;
  onay(komutId: string, kabul: boolean, neden?: string): void;
  cerceve(kayit: CerceveKaydi): void;
  yetki(komutVerebilir: boolean): void;
}

export interface GecitBaglantisi {
  komutGonder(komut: Command): string | null;
  kapat(): void;
  /** Son ölçülen gidiş-dönüş gecikmesi (ms). Henüz ölçülmediyse null. */
  gecikme(): number | null;
}

/**
 * Hareket komutlarının reddedileceği gecikme eşiği.
 *
 * Bunun üstünde operatör gördüğü şeyin geçmişine komut veriyor demektir; kafayı
 * "şu an" sandığı yere çevirmeye çalışırken robot çoktan başka yerde olur.
 */
export const GECIKME_ESIGI_MS = 800;

export function gecideBaglan(
  cihazId: string,
  olaylar: GecitOlaylari,
): GecitBaglantisi {
  let soket: WebSocket | null = null;
  let kapatildi = false;
  let sonGecikme: number | null = null;
  let komutSayaci = 0;

  const kaydet = (yon: CerceveKaydi["yon"], tur: string, ozet: string): void => {
    olaylar.cerceve({ yon, tur, ozet, t: Date.now() });
  };

  const yolla = (cerceve: Record<string, unknown>, ozet: string): void => {
    if (!soket || soket.readyState !== WebSocket.OPEN) return;
    soket.send(JSON.stringify(cerceve));
    kaydet("giden", String(cerceve.kind), ozet);
  };

  void (async () => {
    olaylar.durum("yetkileniyor");

    let token: string;
    let gecitUrl: string;
    try {
      const yanit = await fetch("/api/panel/jeton", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ cihazId }),
      });
      if (!yanit.ok) {
        olaylar.durum("hata", "Bu cihaz için yetki alınamadı.");
        return;
      }
      const govde = (await yanit.json()) as { token: string; gecitUrl: string };
      token = govde.token;
      gecitUrl = govde.gecitUrl;
    } catch {
      olaylar.durum("hata", "Yetki sunucusuna ulaşılamadı.");
      return;
    }

    if (kapatildi) return;
    olaylar.durum("baglaniyor");

    try {
      soket = new WebSocket(`${gecitUrl.replace(/\/$/, "")}/ws/panel`);
    } catch {
      olaylar.durum("hata", "Ağ geçidine bağlanılamadı.");
      return;
    }

    soket.addEventListener("open", () => {
      yolla({ kind: "panel.merhaba", v: PROTOCOL_VERSION, token }, "kimlik");
    });

    soket.addEventListener("message", (olay) => {
      let govde: unknown;
      try {
        govde = JSON.parse(String(olay.data));
      } catch {
        return;
      }

      const cozulmus = gecitPanelCerceveSchema.safeParse(govde);
      if (!cozulmus.success) {
        kaydet("gelen", "?", "sözleşme dışı çerçeve — yok sayıldı");
        return;
      }

      const cerceve = cozulmus.data;

      switch (cerceve.kind) {
        case "gecit.panel-kabul":
          olaylar.yetki(cerceve.komutVerebilir);
          olaylar.durum("bagli");
          kaydet("gelen", cerceve.kind, `cihaz ${cerceve.cihazId.slice(0, 8)}…`);
          break;

        case "gecit.cihaz-durum":
          olaylar.cihazDurumu(cerceve.bagli, cerceve.sonGorulme, cerceve.firmware);
          olaylar.durum(cerceve.bagli ? "bagli" : "robot-yok");
          kaydet("gelen", cerceve.kind, cerceve.bagli ? "robot bağlı" : "robot yok");
          break;

        case "gecit.telemetri": {
          /*
           * Gecikme ağ geçidinin damgasıyla ölçülüyor, robotunkiyle değil:
           * robotun saati bizimkiyle eşitli değil ve fark gecikmeye karışırdı.
           */
          const gecikme = Date.now() - cerceve.t;
          sonGecikme = gecikme;
          olaylar.telemetri(cerceve.payload, gecikme);
          break;
        }

        case "gecit.onay":
          olaylar.onay(cerceve.komutId, cerceve.kabul, cerceve.neden);
          kaydet(
            "gelen",
            cerceve.kind,
            cerceve.kabul ? "komut uygulandı" : `reddedildi: ${cerceve.neden ?? "—"}`,
          );
          break;

        case "gecit.ping":
          yolla({ kind: "panel.pong", t: cerceve.t }, "nabız");
          break;

        case "gecit.hata":
          olaylar.durum("hata", cerceve.mesaj);
          kaydet("gelen", cerceve.kind, `${cerceve.kod}: ${cerceve.mesaj}`);
          break;
      }
    });

    soket.addEventListener("close", () => {
      if (!kapatildi) olaylar.durum("kopuk");
    });

    soket.addEventListener("error", () => {
      if (!kapatildi) olaylar.durum("hata", "Ağ geçidi bağlantısı koptu.");
    });
  })();

  return {
    komutGonder(komut) {
      const komutId = `k${++komutSayaci}`;
      const ozet =
        komut.kind === "head.target"
          ? `hedef ${komut.yawDeg}°`
          : komut.kind === "estop"
            ? komut.engaged
              ? "acil durdurma"
              : "durdurmayı kaldır"
            : "merkeze al";
      yolla({ kind: "panel.komut", komutId, komut }, ozet);
      return komutId;
    },
    kapat() {
      kapatildi = true;
      soket?.close();
    },
    gecikme: () => sonGecikme,
  };
}
