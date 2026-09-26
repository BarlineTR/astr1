import { iyzicoSaglayici } from "./iyzico";
import { sahteSaglayici } from "./sahte";
import type { OdemeSaglayici } from "./saglayici";

export type { OdemeSaglayici, OdemeBaslatGirdi, OdemeSonucu, SepetKalemi } from "./saglayici";

/**
 * Yapılandırmaya göre sağlayıcı seçer.
 *
 * iyzico anahtarları varsa iyzico, yoksa sahte sağlayıcı. **Sessizce** sahteye
 * düşmüyor: seçilen sağlayıcı arayüzde ve günlükte görünüyor, çünkü yanlışlıkla
 * sahte sağlayıcıyla yayına çıkmak paranın hiç tahsil edilmemesi demek.
 *
 * Süreç boyunca tek örnek tutuluyor: sahte sağlayıcı oturumları bellekte ve her
 * çağrıda yeni örnek üretmek onları kaybettiriyordu. Next geliştirme kipinde
 * modülleri sıcak yeniden yüklediği için globalThis üzerinde saklanıyor.
 */
const global_ = globalThis as unknown as { __astroOdeme?: OdemeSaglayici };

function olustur(): OdemeSaglayici {
  const apiKey = process.env.IYZICO_API_KEY;
  const secretKey = process.env.IYZICO_SECRET_KEY;
  const uri = process.env.IYZICO_URI ?? "https://sandbox-api.iyzipay.com";
  const siteUrl = process.env.NEXT_PUBLIC_SITE_URL ?? "http://localhost:3000";

  if (apiKey && secretKey) {
    return iyzicoSaglayici({ apiKey, secretKey, uri });
  }

  return sahteSaglayici(siteUrl);
}

export function odemeSaglayici(): OdemeSaglayici {
  const mevcut = global_.__astroOdeme ?? olustur();
  global_.__astroOdeme = mevcut;
  return mevcut;
}

/** Gerçek para hareket ediyor mu — arayüzde uyarı çizmek için. */
export function odemeCanliMi(): boolean {
  return odemeSaglayici().canli;
}
