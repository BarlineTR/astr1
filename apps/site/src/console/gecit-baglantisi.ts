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

/** Yeniden bağlanma gecikmesi (ms). */
const YENIDEN_BAGLANTI_GECIKME_MS = 5000;

export function gecideBaglan(
  cihazId: string,
  olaylar: GecitOlaylari,
  secenekler?: {
    baslangicJetonu?: string;
    gecitUrl?: string;
  },
): GecitBaglantisi {
  let soket: WebSocket | null = null;
  let kapatildi = false;
  let sonGecikme: number | null = null;
  let komutSayaci = 0;
  let yenidenBaglanmaZamanlayici: ReturnType<typeof setTimeout> | null = null;

  const kaydet = (yon: CerceveKaydi["yon"], tur: string, ozet: string): void => {
    olaylar.cerceve({ yon, tur, ozet, t: Date.now() });
  };

  const yolla = (cerceve: Record<string, unknown>, ozet: string): void => {
    if (!soket || soket.readyState !== WebSocket.OPEN) return;
    soket.send(JSON.stringify(cerceve));
    kaydet("giden", String(cerceve.kind), ozet);
  };

  const baglan = async (): Promise<void> => {
    if (kapatildi) return;
    olaylar.durum("yetkileniyor");

    let token: string = secenekler?.baslangicJetonu ?? "";
    let gecitUrl: string = secenekler?.gecitUrl ?? "";

    if (!token || !gecitUrl) {
      try {
        const yanit = await fetch("/api/panel/jeton", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ cihazId }),
          signal: AbortSignal.timeout(6000),
        });
        if (!yanit.ok) {
          olaylar.durum("hata", "Bu cihaz için yetki alınamadı.");
          planlaYenidenBaglanma();
          return;
        }
        const govde = (await yanit.json()) as { token: string; gecitUrl: string };
        token = govde.token;
        gecitUrl = govde.gecitUrl;
      } catch {
        olaylar.durum("hata", "Yetki sunucusuna ulaşılamadı.");
        planlaYenidenBaglanma();
        return;
      }
    }

    if (kapatildi) return;
    olaylar.durum("baglaniyor");

    try {
      let wsUrl = gecitUrl.replace(/\/$/, "");
      if (typeof window !== "undefined") {
        const curHost = window.location.hostname;
        if (curHost && curHost !== "localhost" && curHost !== "127.0.0.1") {
          wsUrl = wsUrl.replace(/localhost|127\.0\.0\.1/, curHost);
        }
      }
      soket = new WebSocket(`${wsUrl}/ws/panel`);
    } catch {
      olaylar.durum("hata", "Ağ geçidine bağlanılamadı.");
      planlaYenidenBaglanma();
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
      if (!kapatildi) {
        olaylar.durum("kopuk");
        planlaYenidenBaglanma();
      }
    });

    soket.addEventListener("error", () => {
      if (!kapatildi) {
        olaylar.durum("hata", "Ağ geçidi bağlantısı koptu.");
        planlaYenidenBaglanma();
      }
    });
  };

  const planlaYenidenBaglanma = (): void => {
    if (kapatildi) return;
    if (yenidenBaglanmaZamanlayici !== null) return; // Zaten planlandı
    yenidenBaglanmaZamanlayici = setTimeout(() => {
      yenidenBaglanmaZamanlayici = null;
      soket?.close();
      soket = null;
      void baglan();
    }, YENIDEN_BAGLANTI_GECIKME_MS);
  };

  void baglan();

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
      if (yenidenBaglanmaZamanlayici !== null) {
        clearTimeout(yenidenBaglanmaZamanlayici);
        yenidenBaglanmaZamanlayici = null;
      }
      soket?.close();
    },
    gecikme: () => sonGecikme,
  };
}
