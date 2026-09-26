import Iyzipay from "iyzipay";

import { iyzicoSaglayici } from "./iyzico";
import { iyzicoAbonelik } from "./iyzico-abonelik";
import { sahteSaglayici } from "./sahte";
import { sahteAbonelik } from "./sahte-abonelik";
import type { AbonelikSaglayici, OdemeSaglayici } from "./saglayici";

export type {
  AbonelikSaglayici,
  AbonelikSonucu,
  OdemeSaglayici,
  OdemeBaslatGirdi,
  OdemeSonucu,
  SepetKalemi,
} from "./saglayici";
export { abonelikDestekliyorMu } from "./saglayici";

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
    /*
     * Abonelik yüzeyi aynı istemciyi paylaşıyor ama ayrı bir modülde: iyzico'da
     * abonelik ayrı bir ürün ve hesapta ayrıca etkinleştirilmesi gerekiyor.
     * Tek seferlik ödeme çalışırken aboneliğin çalışmaması olağan bir durum.
     */
    const istemci = new Iyzipay({ apiKey, secretKey, uri });
    return Object.assign(
      iyzicoSaglayici({ apiKey, secretKey, uri }),
      iyzicoAbonelik(istemci),
    );
  }

  return Object.assign(sahteSaglayici(siteUrl), sahteAbonelik(siteUrl));
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
