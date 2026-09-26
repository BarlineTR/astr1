import Iyzipay from "iyzipay";

import { kurusuDizgiye, dizgidenKurusa, sepetToplamiDogrula } from "./tutar";
import type {
  OdemeBaslatGirdi,
  OdemeBaslatSonuc,
  OdemeSaglayici,
  OdemeSonucu,
} from "./saglayici";

/**
 * iyzico — Checkout Form akışı.
 *
 *   1. `initialize` → token + ödeme sayfası adresi
 *   2. Kullanıcı iyzico'nun sayfasında öder (3D Secure orada yürür)
 *   3. iyzico geri dönüş adresimize **yalnızca token** POST eder
 *   4. `retrieve` ile sonucu kendi anahtarlarımızla sorarız
 *
 * Güvenin dayandığı yer 4. adım: geri dönüşte gelen tek şey token ve sonucu
 * biz kimlik doğrulamalı bir API çağrısıyla alıyoruz. Bu yüzden sahte bir geri
 * dönüş isteği başarılı bir ödeme uyduramaz — kart bilgisi de hiçbir zaman
 * bizim sunucumuza uğramaz.
 */

type IyzicoYanit = Iyzipay.Yanit;

/**
 * `paidPrice` hem dizgi hem sayı gelebiliyor.
 *
 * Sayı geldiğinde `String()` "199.9" üretiyor ve ayrıştırıcımız bunu zaten
 * yüz kuruşa tamamlıyor; ama kayan noktalı gösterimden geçtiği için önce
 * iki basamağa sabitleniyor.
 */
function tutarKurusa(deger: string | number | undefined): number | undefined {
  if (deger === undefined) return undefined;
  return dizgidenKurusa(typeof deger === "number" ? deger.toFixed(2) : deger);
}

/** SDK geri çağırmalı; söz veren bir kabuk içine alıyoruz. */
function sozVer<T>(
  cagir: (geriCagir: (hata: unknown, sonuc: T) => void) => void,
): Promise<T> {
  return new Promise((coz, reddet) => {
    cagir((hata, sonuc) => (hata ? reddet(hata) : coz(sonuc)));
  });
}

export function iyzicoSaglayici(ayar: {
  apiKey: string;
  secretKey: string;
  uri: string;
}): OdemeSaglayici {
  const istemci = new Iyzipay({
    apiKey: ayar.apiKey,
    secretKey: ayar.secretKey,
    uri: ayar.uri,
  });

  // Sandbox anahtarları "sandbox-" ile başlıyor; canlı olup olmadığımızı
  // arayüzde göstermek için gerekli.
  const canli = !ayar.apiKey.startsWith("sandbox-") && !ayar.uri.includes("sandbox");

  return {
    id: "iyzico",
    canli,

    async odemeBaslat(girdi: OdemeBaslatGirdi): Promise<OdemeBaslatSonuc> {
      /*
       * Sepet toplamı ile beyan edilen tutar birebir eşit olmalı; iyzico bir
       * kuruşluk farkta isteği tamamen reddediyor ve döndürdüğü hata
       * kullanıcıya gösterilemeyecek kadar genel.
       */
      sepetToplamiDogrula(girdi.kalemler, girdi.toplamKurus);

      const tutar = kurusuDizgiye(girdi.toplamKurus);

      const istek = {
        locale: Iyzipay.LOCALE.TR,
        conversationId: girdi.conversationId,
        price: tutar,
        // Taksit farkı uygulanmadığı için ikisi aynı.
        paidPrice: tutar,
        currency: girdi.paraBirimi,
        basketId: girdi.siparisId,
        paymentGroup: Iyzipay.PAYMENT_GROUP.PRODUCT,
        callbackUrl: girdi.geriDonusUrl,
        enabledInstallments: [1],
        buyer: {
          id: girdi.alici.id,
          name: girdi.alici.ad,
          surname: girdi.alici.soyad,
          email: girdi.alici.eposta,
          identityNumber: "11111111111",
          registrationAddress: girdi.alici.adres ?? "Bilgi verilmedi",
          ip: girdi.alici.ip,
          city: girdi.alici.sehir ?? "Istanbul",
          country: girdi.alici.ulke ?? "Turkey",
          ...(girdi.alici.telefon ? { gsmNumber: girdi.alici.telefon } : {}),
        },
        billingAddress: {
          contactName: `${girdi.alici.ad} ${girdi.alici.soyad}`.trim(),
          city: girdi.alici.sehir ?? "Istanbul",
          country: girdi.alici.ulke ?? "Turkey",
          address: girdi.alici.adres ?? "Bilgi verilmedi",
        },
        /*
         * Kargo adresi yok: bütün kalemler VIRTUAL. Fiziksel ürün satışı
         * başladığında (e-ticaret fazı) shippingAddress zorunlu olacak.
         */
        basketItems: girdi.kalemler.map((k) => ({
          id: k.slug,
          name: k.ad,
          category1: "Dijital",
          itemType: Iyzipay.BASKET_ITEM_TYPE.VIRTUAL,
          price: kurusuDizgiye(k.birimKurus * k.adet),
        })),
      };

      try {
        const yanit = await sozVer<IyzicoYanit>((gc) =>
          istemci.checkoutFormInitialize.create(istek, gc),
        );

        if (yanit.status !== "success" || !yanit.token || !yanit.paymentPageUrl) {
          return {
            ok: false,
            hata: yanit.errorMessage ?? "Ödeme başlatılamadı.",
          };
        }

        return { ok: true, token: yanit.token, odemeSayfasiUrl: yanit.paymentPageUrl };
      } catch (hata) {
        return { ok: false, hata: `Ödeme sağlayıcısına ulaşılamadı: ${String(hata)}` };
      }
    },

    async sonucuAl(token: string): Promise<OdemeSonucu> {
      try {
        const yanit = await sozVer<IyzicoYanit>((gc) =>
          istemci.checkoutForm.retrieve({ locale: Iyzipay.LOCALE.TR, token }, gc),
        );

        if (yanit.status !== "success") {
          return {
            ok: false,
            durum: "basarisiz",
            hata: yanit.errorMessage ?? "Ödeme doğrulanamadı.",
            conversationId: yanit.conversationId,
            ham: yanit,
          };
        }

        const basarili = yanit.paymentStatus === "SUCCESS";

        return {
          ok: true,
          odemeId: yanit.paymentId,
          durum: basarili ? "basarili" : "basarisiz",
          tutarKurus: tutarKurusa(yanit.paidPrice),
          paraBirimi: yanit.currency,
          conversationId: yanit.conversationId,
          kartAilesi: yanit.cardFamily,
          kartSonDort: yanit.lastFourDigits,
          ham: yanit,
        };
      } catch (hata) {
        return {
          ok: false,
          durum: "bilinmiyor",
          hata: `Sonuç alınamadı: ${String(hata)}`,
          ham: null,
        };
      }
    },
  };
}
