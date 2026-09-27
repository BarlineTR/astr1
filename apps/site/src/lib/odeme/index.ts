import Iyzipay from "iyzipay";

import { iyzicoSaglayici } from "./iyzico";
import { iyzicoAbonelik } from "./iyzico-abonelik";
import { sahteSaglayici } from "./sahte";
import { sahteAbonelik } from "./sahte-abonelik";
import { stripeSaglayici } from "./stripe";
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
 * 1. Stripe anahtarı (STRIPE_SECRET_KEY) varsa -> Stripe
 * 2. iyzico anahtarları (IYZICO_API_KEY & IYZICO_SECRET_KEY) varsa -> iyzico
 * 3. Hiçbiri yoksa -> Sahte sağlayıcı (Test / Geliştirme)
 */
const global_ = globalThis as unknown as { __astroOdeme?: OdemeSaglayici };

function olustur(): OdemeSaglayici {
  const stripeSecret = process.env.STRIPE_SECRET_KEY;
  const stripePublishable = process.env.STRIPE_PUBLISHABLE_KEY || process.env.NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY;
  const stripeWebhook = process.env.STRIPE_WEBHOOK_SECRET;

  if (stripeSecret) {
    return stripeSaglayici({
      secretKey: stripeSecret,
      publishableKey: stripePublishable,
      webhookSecret: stripeWebhook,
    });
  }

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
