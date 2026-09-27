import Stripe from "stripe";

import type {
  AbonelikBaslatGirdi,
  AbonelikBaslatSonuc,
  AbonelikSaglayici,
  AbonelikSonucu,
  OdemeBaslatGirdi,
  OdemeBaslatSonuc,
  OdemeSaglayici,
  OdemeSonucu,
} from "./saglayici";
import { kurusuDizgiye, sepetToplamiDogrula } from "./tutar";

/**
 * Stripe — Checkout Session & Subscription Entegrasyonu.
 *
 * Stripe API anahtarı (.env.local içinde STRIPE_SECRET_KEY) tanımlandığında
 * otomatik olarak devreye girer. Tanımlı değilse sistem iyzico veya test moduna geçer.
 *
 * Güvenlik Invariantı:
 *   - Stripe Secret Key ASLA istemciye/tarayıcıya sızdırılmaz.
 *   - Kart numaraları sunucumuza hiç uğramaz (PCI-DSS uyumlu Hosted Checkout).
 */

export function stripeSaglayici(ayar: {
  secretKey: string;
  publishableKey?: string;
  webhookSecret?: string;
}): OdemeSaglayici & AbonelikSaglayici {
  const stripe = new Stripe(ayar.secretKey, {
    apiVersion: "2025-02-24.acacia" as any,
  });

  const canli = ayar.secretKey.startsWith("sk_live_");

  return {
    id: "stripe",
    canli,

    async odemeBaslat(girdi: OdemeBaslatGirdi): Promise<OdemeBaslatSonuc> {
      sepetToplamiDogrula(girdi.kalemler, girdi.toplamKurus);

      try {
        const lineItems: Stripe.Checkout.SessionCreateParams.LineItem[] = girdi.kalemler.map((k) => ({
          price_data: {
            currency: (girdi.paraBirimi || "try").toLowerCase(),
            product_data: {
              name: k.ad,
              description: `Ürün kodu: ${k.slug}`,
            },
            unit_amount: k.birimKurus,
          },
          quantity: k.adet,
        }));

        const session = await stripe.checkout.sessions.create({
          payment_method_types: ["card"],
          line_items: lineItems,
          mode: "payment",
          customer_email: girdi.alici.eposta,
          client_reference_id: girdi.siparisId,
          metadata: {
            siparisId: girdi.siparisId,
            conversationId: girdi.conversationId,
            aliciId: girdi.alici.id,
            aliciAdSoyad: `${girdi.alici.ad} ${girdi.alici.soyad}`.trim(),
          },
          success_url: `${girdi.geriDonusUrl}?session_id={CHECKOUT_SESSION_ID}&durum=basarili`,
          cancel_url: `${girdi.geriDonusUrl}?session_id={CHECKOUT_SESSION_ID}&durum=iptal`,
        });

        if (!session.url || !session.id) {
          return {
            ok: false,
            hata: "Stripe ödeme oturumu başlatılamadı.",
          };
        }

        return {
          ok: true,
          token: session.id,
          odemeSayfasiUrl: session.url,
        };
      } catch (hata: any) {
        return {
          ok: false,
          hata: `Stripe oturumu açılamadı: ${hata?.message ?? String(hata)}`,
        };
      }
    },

    async sonucuAl(token: string): Promise<OdemeSonucu> {
      try {
        const session = await stripe.checkout.sessions.retrieve(token, {
          expand: ["payment_intent", "payment_intent.payment_method"],
        });

        const isPaid = session.payment_status === "paid";
        const pi = session.payment_intent as Stripe.PaymentIntent | null;
        const pm = pi?.payment_method as Stripe.PaymentMethod | null;

        return {
          ok: isPaid,
          odemeId: typeof session.payment_intent === "string" ? session.payment_intent : session.payment_intent?.id,
          durum: isPaid ? "basarili" : "basarisiz",
          tutarKurus: session.amount_total ?? undefined,
          paraBirimi: (session.currency ?? "try").toUpperCase(),
          conversationId: session.metadata?.conversationId,
          kartAilesi: pm?.card?.brand ?? undefined,
          kartSonDort: pm?.card?.last4 ?? undefined,
          hata: isPaid ? undefined : "Ödeme henüz onaylanmadı veya başarısız oldu.",
          ham: session,
        };
      } catch (hata: any) {
        return {
          ok: false,
          durum: "bilinmiyor",
          hata: `Stripe sonucu sorgulanamadı: ${hata?.message ?? String(hata)}`,
          ham: null,
        };
      }
    },

    /* ────────────────────────────  Abonelik  ──────────────────────────── */

    async abonelikBaslat(girdi: AbonelikBaslatGirdi): Promise<AbonelikBaslatSonuc> {
      try {
        const session = await stripe.checkout.sessions.create({
          payment_method_types: ["card"],
          mode: "subscription",
          customer_email: girdi.alici.eposta,
          client_reference_id: girdi.abonelikId,
          line_items: [
            {
              price: girdi.planRef,
              quantity: 1,
            },
          ],
          metadata: {
            abonelikId: girdi.abonelikId,
            conversationId: girdi.conversationId,
            aliciId: girdi.alici.id,
          },
          success_url: `${girdi.geriDonusUrl}?session_id={CHECKOUT_SESSION_ID}&durum=basarili`,
          cancel_url: `${girdi.geriDonusUrl}?session_id={CHECKOUT_SESSION_ID}&durum=iptal`,
        });

        if (!session.url || !session.id) {
          return {
            ok: false,
            hata: "Stripe abonelik oturumu başlatılamadı.",
          };
        }

        return {
          ok: true,
          token: session.id,
          odemeSayfasiUrl: session.url,
        };
      } catch (hata: any) {
        return {
          ok: false,
          hata: `Stripe abonelik başlatılamadı: ${hata?.message ?? String(hata)}`,
        };
      }
    },

    async abonelikSonucuAl(token: string): Promise<AbonelikSonucu> {
      try {
        const session = await stripe.checkout.sessions.retrieve(token, {
          expand: ["subscription"],
        });

        const sub = session.subscription as Stripe.Subscription | null;
        if (!sub) {
          return {
            ok: false,
            durum: "bekliyor",
            hata: "Abonelik kaydı bulunamadı.",
            ham: session,
          };
        }

        const durumMap: Record<Stripe.Subscription.Status, AbonelikSonucu["durum"]> = {
          active: "aktif",
          trialing: "aktif",
          incomplete: "bekliyor",
          incomplete_expired: "bitti",
          past_due: "odenmedi",
          canceled: "iptal",
          unpaid: "odenmedi",
          paused: "bekliyor",
        };

        const donemSonu = (sub as any).current_period_end
          ? (sub as any).current_period_end * 1000
          : undefined;

        return {
          ok: sub.status === "active" || sub.status === "trialing",
          abonelikRef: sub.id,
          durum: durumMap[sub.status] ?? "bekliyor",
          donemSonu,
          conversationId: session.metadata?.conversationId,
          ham: sub,
        };
      } catch (hata: any) {
        return {
          ok: false,
          durum: "bekliyor",
          hata: `Stripe abonelik sonucu alınamadı: ${hata?.message ?? String(hata)}`,
          ham: null,
        };
      }
    },

    async abonelikDurumAl(abonelikRef: string): Promise<AbonelikSonucu> {
      try {
        const sub = await stripe.subscriptions.retrieve(abonelikRef);
        const durumMap: Record<Stripe.Subscription.Status, AbonelikSonucu["durum"]> = {
          active: "aktif",
          trialing: "aktif",
          incomplete: "bekliyor",
          incomplete_expired: "bitti",
          past_due: "odenmedi",
          canceled: "iptal",
          unpaid: "odenmedi",
          paused: "bekliyor",
        };

        const donemSonu = (sub as any).current_period_end
          ? (sub as any).current_period_end * 1000
          : undefined;

        return {
          ok: sub.status === "active" || sub.status === "trialing",
          abonelikRef: sub.id,
          durum: durumMap[sub.status] ?? "bekliyor",
          donemSonu,
          ham: sub,
        };
      } catch (hata: any) {
        return {
          ok: false,
          durum: "bekliyor",
          hata: `Stripe abonelik durumu sorgulanamadı: ${hata?.message ?? String(hata)}`,
          ham: null,
        };
      }
    },

    async abonelikIptal(abonelikRef: string): Promise<{ ok: boolean; hata?: string }> {
      try {
        await stripe.subscriptions.cancel(abonelikRef);
        return { ok: true };
      } catch (hata: any) {
        return {
          ok: false,
          hata: `Stripe abonelik iptal edilemedi: ${hata?.message ?? String(hata)}`,
        };
      }
    },
  };
}
