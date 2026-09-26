import Iyzipay from "iyzipay";

import type {
  AbonelikBaslatGirdi,
  AbonelikBaslatSonuc,
  AbonelikDurumu,
  AbonelikSaglayici,
  AbonelikSonucu,
} from "./saglayici";

/**
 * iyzico abonelik uygulaması.
 *
 * Akış tek seferlik ödemeye benziyor ama önemli bir farkı var: **fiyat planı
 * iyzico tarafında yaşıyor.** Ürün ve plan iyzico panelinden (ya da API'sinden)
 * oluşturuluyor ve bize bir `pricingPlanReferenceCode` veriyor; tutar ve
 * yenileme sıklığı orada tanımlı. Biz yalnızca o referansı gönderiyoruz.
 *
 * Bu yüzden `data/fiyatlar.ts` içindeki tutar **gösterim** amaçlı; tahsil edilen
 * tutarı iyzico'daki plan belirliyor. İkisinin ayrışmaması gerekiyor ve bunu
 * `IYZICO_PLAN_*` eşlemesini kuran kişi sağlamak zorunda — kod bunu doğrulayamaz
 * çünkü plan tutarını ancak iyzico biliyor.
 *
 * Tekrarlayan çekimi iyzico yürütüyor: kartı o saklıyor, yenileme tarihinde o
 * çekiyor. Kendi zamanlayıcımızla çekim denemek, sağlayıcının durumuyla ayrışan
 * ikinci bir gerçek üretirdi.
 */

type IyzicoYanit = Iyzipay.Yanit;

function sozVer<T>(cagir: (gc: (h: unknown, s: T) => void) => void): Promise<T> {
  return new Promise((coz, reddet) => {
    cagir((hata, sonuc) => (hata ? reddet(hata) : coz(sonuc)));
  });
}

/** iyzico abonelik durumlarını bizimkilere çevirir. */
function durumCevir(iyzicoDurum: unknown): AbonelikDurumu {
  switch (String(iyzicoDurum)) {
    case "ACTIVE":
      return "aktif";
    case "PENDING":
      return "bekliyor";
    case "UNPAID":
      return "odenmedi";
    case "CANCELED":
      return "iptal";
    case "EXPIRED":
      return "bitti";
    default:
      return "bekliyor";
  }
}

export function iyzicoAbonelik(istemci: Iyzipay): AbonelikSaglayici {
  return {
    async abonelikBaslat(girdi: AbonelikBaslatGirdi): Promise<AbonelikBaslatSonuc> {
      try {
        const yanit = await sozVer<IyzicoYanit>((gc) =>
          istemci.subscriptionCheckoutForm.initialize(
            {
              locale: Iyzipay.LOCALE.TR,
              conversationId: girdi.conversationId,
              callbackUrl: girdi.geriDonusUrl,
              pricingPlanReferenceCode: girdi.planRef,
              customer: {
                name: girdi.alici.ad,
                surname: girdi.alici.soyad,
                email: girdi.alici.eposta,
                identityNumber: "11111111111",
                ...(girdi.alici.telefon ? { gsmNumber: girdi.alici.telefon } : {}),
                billingAddress: {
                  contactName: `${girdi.alici.ad} ${girdi.alici.soyad}`.trim(),
                  city: girdi.alici.sehir ?? "Istanbul",
                  country: girdi.alici.ulke ?? "Turkey",
                  address: girdi.alici.adres ?? "Bilgi verilmedi",
                },
              },
            },
            gc,
          ),
        );

        const veri = (yanit.data ?? yanit) as Record<string, unknown>;
        const token = veri.token as string | undefined;
        const url = veri.checkoutFormContent
          ? undefined
          : (veri.paymentPageUrl as string | undefined);

        if (yanit.status !== "success" || !token) {
          return { ok: false, hata: yanit.errorMessage ?? "Abonelik başlatılamadı." };
        }

        return { ok: true, token, odemeSayfasiUrl: url };
      } catch (hata) {
        return { ok: false, hata: `Sağlayıcıya ulaşılamadı: ${String(hata)}` };
      }
    },

    async abonelikSonucuAl(token: string): Promise<AbonelikSonucu> {
      try {
        const yanit = await sozVer<IyzicoYanit>((gc) =>
          istemci.subscriptionCheckoutForm.retrieve({ checkoutFormToken: token }, gc),
        );
        return yanitiCevir(yanit);
      } catch (hata) {
        return { ok: false, durum: "bekliyor", hata: String(hata), ham: null };
      }
    },

    async abonelikDurumAl(abonelikRef: string): Promise<AbonelikSonucu> {
      try {
        const yanit = await sozVer<IyzicoYanit>((gc) =>
          istemci.subscription.retrieve({ subscriptionReferenceCode: abonelikRef }, gc),
        );
        return yanitiCevir(yanit);
      } catch (hata) {
        return { ok: false, durum: "bekliyor", hata: String(hata), ham: null };
      }
    },

    async abonelikIptal(abonelikRef: string): Promise<{ ok: boolean; hata?: string }> {
      try {
        const yanit = await sozVer<IyzicoYanit>((gc) =>
          istemci.subscription.cancel({ subscriptionReferenceCode: abonelikRef }, gc),
        );
        if (yanit.status !== "success") {
          return { ok: false, hata: yanit.errorMessage ?? "İptal edilemedi." };
        }
        return { ok: true };
      } catch (hata) {
        return { ok: false, hata: String(hata) };
      }
    },
  };
}

function yanitiCevir(yanit: IyzicoYanit): AbonelikSonucu {
  const veri = (yanit.data ?? yanit) as Record<string, unknown>;

  if (yanit.status !== "success") {
    return {
      ok: false,
      durum: "bekliyor",
      hata: yanit.errorMessage ?? "Abonelik durumu alınamadı.",
      conversationId: yanit.conversationId,
      ham: yanit,
    };
  }

  const donemSonu = veri.endDate ?? veri.startDate;

  return {
    ok: true,
    abonelikRef: veri.referenceCode as string | undefined,
    durum: durumCevir(veri.subscriptionStatus ?? veri.status),
    donemSonu: typeof donemSonu === "number" ? donemSonu : undefined,
    conversationId: yanit.conversationId,
    ham: yanit,
  };
}
