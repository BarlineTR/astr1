import { randomUUID } from "node:crypto";

import type {
  AbonelikBaslatGirdi,
  AbonelikBaslatSonuc,
  AbonelikDurumu,
  AbonelikSaglayici,
  AbonelikSonucu,
} from "./saglayici";

/**
 * Sahte abonelik sağlayıcısı.
 *
 * Gerçekte yenilemeyi sağlayıcı yürütüyor ve bunu beklemek testte mümkün değil;
 * burada yenilemeyi elle tetikleyebiliyoruz. Böylece "bir ay sonra ne oluyor"
 * sorusu bir ay beklemeden sınanabiliyor.
 */

const AY_MS = 30 * 24 * 60 * 60 * 1000;

interface Oturum {
  girdi: AbonelikBaslatGirdi;
  ref: string | null;
  durum: AbonelikDurumu;
  donemSonu: number | null;
}

export interface SahteAbonelikEk {
  sahteAbonelikOzeti(token: string): {
    tutarKurus: number;
    kalemAdi: string;
    periyot: "ay";
  } | null;
  sahteAbonelikKarar(token: string, sonuc: "basarili" | "basarisiz"): boolean;
  /** Bir dönem ilerletir — gerçekte sağlayıcının yenileme çekimi. */
  sahteAbonelikYenile(ref: string): boolean;
  /** Yenileme başarısız olduysa: kart reddedildi. */
  sahteAbonelikOdenmedi(ref: string): boolean;
}

export function sahteAbonelik(
  siteUrl: string,
): AbonelikSaglayici & SahteAbonelikEk {
  const oturumlar = new Map<string, Oturum>();
  const referanslar = new Map<string, Oturum>();

  return {
    async abonelikBaslat(girdi: AbonelikBaslatGirdi): Promise<AbonelikBaslatSonuc> {
      const token = `sahteab_${randomUUID()}`;
      oturumlar.set(token, { girdi, ref: null, durum: "bekliyor", donemSonu: null });
      return {
        ok: true,
        token,
        odemeSayfasiUrl: `${siteUrl}/odeme/sahte-abonelik/${token}`,
      };
    },

    async abonelikSonucuAl(token: string): Promise<AbonelikSonucu> {
      const oturum = oturumlar.get(token);
      if (!oturum) {
        return { ok: false, durum: "bekliyor", hata: "Bilinmeyen oturum", ham: null };
      }
      return {
        ok: true,
        abonelikRef: oturum.ref ?? undefined,
        durum: oturum.durum,
        donemSonu: oturum.donemSonu ?? undefined,
        conversationId: oturum.girdi.conversationId,
        ham: { sahte: true, token, durum: oturum.durum },
      };
    },

    async abonelikDurumAl(ref: string): Promise<AbonelikSonucu> {
      const oturum = referanslar.get(ref);
      if (!oturum) {
        return { ok: false, durum: "bekliyor", hata: "Bilinmeyen abonelik", ham: null };
      }
      return {
        ok: true,
        abonelikRef: ref,
        durum: oturum.durum,
        donemSonu: oturum.donemSonu ?? undefined,
        ham: { sahte: true, ref, durum: oturum.durum },
      };
    },

    async abonelikIptal(ref: string): Promise<{ ok: boolean; hata?: string }> {
      const oturum = referanslar.get(ref);
      if (!oturum) return { ok: false, hata: "Bilinmeyen abonelik" };
      oturum.durum = "iptal";
      return { ok: true };
    },

    sahteAbonelikOzeti(token: string) {
      const oturum = oturumlar.get(token);
      if (!oturum) return null;
      return {
        tutarKurus: oturum.girdi.fiyatKurus,
        kalemAdi: oturum.girdi.planAdi,
        periyot: "ay" as const,
      };
    },

    sahteAbonelikKarar(token: string, sonuc: "basarili" | "basarisiz"): boolean {
      const oturum = oturumlar.get(token);
      if (!oturum) return false;

      if (sonuc === "basarisiz") {
        oturum.durum = "odenmedi";
        return true;
      }

      // Referans ilk başarılı çekimde üretiliyor; gerçekte de öyle.
      oturum.ref ??= `sahte-ab-${token.slice(-12)}`;
      oturum.durum = "aktif";
      oturum.donemSonu = Date.now() + AY_MS;
      referanslar.set(oturum.ref, oturum);
      return true;
    },

    sahteAbonelikYenile(ref: string): boolean {
      const oturum = referanslar.get(ref);
      if (!oturum || oturum.durum === "iptal") return false;
      oturum.durum = "aktif";
      oturum.donemSonu = (oturum.donemSonu ?? Date.now()) + AY_MS;
      return true;
    },

    sahteAbonelikOdenmedi(ref: string): boolean {
      const oturum = referanslar.get(ref);
      if (!oturum) return false;
      oturum.durum = "odenmedi";
      return true;
    },
  };
}
