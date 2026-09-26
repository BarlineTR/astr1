import { randomUUID } from "node:crypto";

import { sepetToplamiDogrula } from "./tutar";
import type {
  OdemeBaslatGirdi,
  OdemeBaslatSonuc,
  OdemeSaglayici,
  OdemeSonucu,
} from "./saglayici";

/**
 * Sahte ödeme sağlayıcısı — geliştirme ve test için.
 *
 * iyzico anahtarları olmadan da bütün sipariş yaşam döngüsünün uçtan uca
 * koşabilmesi gerekiyor: sipariş oluşturma, yönlendirme, sonucun alınması,
 * idempotensi. Anahtar gerektiren bir akış CI'da hiç sınanamazdı.
 *
 * Gerçek sağlayıcıyla aynı arayüzü uyguluyor ve aynı doğrulamaları yapıyor —
 * sepet toplamı kontrolü dahil — ki sahtede geçip gerçekte patlayan bir hata
 * olmasın.
 *
 * Kullanıcıyı kendi sitemizdeki bir "ödeme sayfası taklidi"ne yönlendiriyor;
 * orada ödemeyi onaylamak ya da reddetmek seçilebiliyor.
 */
export function sahteSaglayici(siteUrl: string): OdemeSaglayici {
  const oturumlar = new Map<
    string,
    { girdi: OdemeBaslatGirdi; sonuc: "basarili" | "basarisiz" | null }
  >();

  return {
    id: "sahte",
    canli: false,

    async odemeBaslat(girdi: OdemeBaslatGirdi): Promise<OdemeBaslatSonuc> {
      sepetToplamiDogrula(girdi.kalemler, girdi.toplamKurus);

      const token = `sahte_${randomUUID()}`;
      oturumlar.set(token, { girdi, sonuc: null });

      return {
        ok: true,
        token,
        odemeSayfasiUrl: `${siteUrl}/odeme/sahte/${token}`,
      };
    },

    async sonucuAl(token: string): Promise<OdemeSonucu> {
      const oturum = oturumlar.get(token);
      if (!oturum) {
        return { ok: false, durum: "bilinmiyor", hata: "Bilinmeyen oturum", ham: null };
      }

      /*
       * Karar taklit sayfasında verildi; verilmediyse ödeme henüz
       * tamamlanmamış demektir.
       */
      const durum = oturum.sonuc ?? "basarisiz";

      return {
        ok: true,
        /*
         * Ödeme kimliği token'dan türetiliyor ve sabit: sonucu iki kez almak
         * ikinci bir ödeme kaydı yaratmamalı, idempotensi buna dayanıyor.
         */
        odemeId: `sahte-odeme-${token.slice(-12)}`,
        durum,
        tutarKurus: oturum.girdi.toplamKurus,
        paraBirimi: oturum.girdi.paraBirimi,
        conversationId: oturum.girdi.conversationId,
        kartAilesi: "Sahte Kart",
        kartSonDort: "4242",
        ham: { sahte: true, token, durum },
      };
    },

    /** Yalnızca sahte sağlayıcıda var: taklit sayfası kararı buradan bildirir. */
    ...({
      sahteKararVer(token: string, sonuc: "basarili" | "basarisiz"): boolean {
        const oturum = oturumlar.get(token);
        if (!oturum) return false;
        oturum.sonuc = sonuc;
        return true;
      },
      sahteOturumVarMi(token: string): boolean {
        return oturumlar.has(token);
      },
      sahteOturumOzeti(token: string) {
        const oturum = oturumlar.get(token);
        if (!oturum) return null;
        const ilk = oturum.girdi.kalemler[0];
        return {
          tutarKurus: oturum.girdi.toplamKurus,
          kalemAdi: ilk?.ad ?? "Sipariş",
          periyot: oturum.girdi.periyot ?? "tek",
        };
      },
    } as Record<string, unknown>),
  } as OdemeSaglayici;
}

/** Taklit ekranın göstereceği özet. */
export interface SahteOturumOzeti {
  tutarKurus: number;
  kalemAdi: string;
  periyot: "tek" | "ay";
}

/** Sahte sağlayıcının ek yüzeyi. */
export interface SahteSaglayiciEk {
  sahteKararVer(token: string, sonuc: "basarili" | "basarisiz"): boolean;
  sahteOturumVarMi(token: string): boolean;
  sahteOturumOzeti(token: string): SahteOturumOzeti | null;
}
