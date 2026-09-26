import { randomUUID } from "node:crypto";

import { and, eq, inArray } from "drizzle-orm";

import { db } from "@/db";
import { subscriptions } from "@/db/schema";
import { PLANLAR } from "@/data/fiyatlar";

import { abonelikDestekliyorMu, odemeSaglayici } from "./index";
import type { AbonelikDurumu } from "./saglayici";

/** Abonelik sayılan durumlar: kullanıcı bunlardan biriyle ikinci abonelik açamaz. */
const CANLI_DURUMLAR = ["bekliyor", "aktif", "odenmedi"] as const;

/**
 * Plan slug'ı → sağlayıcıdaki fiyat planı referansı.
 *
 * Plan iyzico tarafında yaşıyor: tutar ve yenileme sıklığı orada tanımlı ve
 * tahsil edilen tutarı o belirliyor. `data/fiyatlar.ts` içindeki tutar
 * **gösterim** amaçlı; ikisinin ayrışmaması eşlemeyi kuran kişinin sorumluluğu,
 * çünkü plan tutarını ancak iyzico biliyor.
 */
export function planReferansi(slug: string): string | null {
  const anahtar = `IYZICO_PLAN_${slug.toUpperCase().replace(/[^A-Z0-9]/g, "_")}`;
  return process.env[anahtar] ?? null;
}

export interface AbonelikBaslatSonucu {
  ok: boolean;
  odemeSayfasiUrl?: string;
  hata?: string;
}

/** Kullanıcının canlı aboneliği (varsa). */
export async function aktifAbonelik(kullaniciId: string) {
  const [satir] = await db
    .select()
    .from(subscriptions)
    .where(
      and(
        eq(subscriptions.userId, kullaniciId),
        inArray(subscriptions.status, [...CANLI_DURUMLAR]),
      ),
    )
    .limit(1);
  return satir ?? null;
}

/**
 * Abonelik başlatır.
 *
 * Kayıt sağlayıcıya gitmeden önce yazılıyor: çağrı başarılı olup yanıt bize
 * ulaşmadan koparsa, kullanıcı abone olmuş ama bizde kaydı yok olurdu.
 */
export async function abonelikBaslat(girdi: {
  kullaniciId: string;
  eposta: string;
  ad: string;
  soyad: string;
  ip: string;
  planSlug: string;
  siteUrl: string;
}): Promise<AbonelikBaslatSonucu> {
  const saglayici = odemeSaglayici();
  if (!abonelikDestekliyorMu(saglayici)) {
    return { ok: false, hata: "Ödeme sağlayıcısı tekrarlayan tahsilatı desteklemiyor." };
  }

  const plan = PLANLAR.find((p) => p.slug === girdi.planSlug);
  if (!plan) return { ok: false, hata: "Plan bulunamadı." };

  const mevcut = await aktifAbonelik(girdi.kullaniciId);
  if (mevcut) {
    /*
     * İkinci abonelik açmak iki kez tahsilat demek. İptal edilmiş ama dönemi
     * sürmekte olan abonelik de buna dahil: dönem bitmeden yenisini açmak,
     * aynı ay için iki kez ödeme demek olurdu.
     */
    return {
      ok: false,
      hata: mevcut.cancelAt
        ? "Aboneliğiniz dönem sonunda bitecek; o tarihten sonra yeni plan seçebilirsiniz."
        : "Zaten bir aboneliğiniz var. Önce mevcut planı iptal edin.",
    };
  }

  /*
   * Gerçek sağlayıcıda plan referansı zorunlu. Sahte sağlayıcıda referans
   * anlamsız, o yüzden slug kullanılıyor — eşleme kurulmadan da akış
   * sınanabilsin.
   */
  const planRef = planReferansi(plan.slug) ?? (saglayici.id === "sahte" ? plan.slug : null);
  if (!planRef) {
    return {
      ok: false,
      hata: `Bu plan sağlayıcıda tanımlı değil (IYZICO_PLAN_${plan.slug.toUpperCase()} eksik).`,
    };
  }

  const abonelikId = randomUUID();
  const conversationId = `astro-ab-${abonelikId}`;

  await db.insert(subscriptions).values({
    id: abonelikId,
    userId: girdi.kullaniciId,
    productSlug: plan.slug,
    provider: saglayici.id,
    status: "bekliyor",
    priceMinor: plan.fiyatKurus,
    currency: "TRY",
  });

  const baslat = await saglayici.abonelikBaslat({
    abonelikId,
    conversationId,
    planRef,
    planAdi: plan.ad,
    fiyatKurus: plan.fiyatKurus,
    alici: {
      id: girdi.kullaniciId,
      ad: girdi.ad,
      soyad: girdi.soyad,
      eposta: girdi.eposta,
      ip: girdi.ip,
    },
    geriDonusUrl: `${girdi.siteUrl}/api/odeme/abonelik-geri-donus`,
  });

  if (!baslat.ok || !baslat.odemeSayfasiUrl) {
    await db
      .update(subscriptions)
      .set({ status: "iptal" })
      .where(eq(subscriptions.id, abonelikId));
    return { ok: false, hata: baslat.hata ?? "Abonelik başlatılamadı." };
  }

  await db
    .update(subscriptions)
    .set({ providerRef: baslat.token ?? null })
    .where(eq(subscriptions.id, abonelikId));

  return { ok: true, odemeSayfasiUrl: baslat.odemeSayfasiUrl };
}

/**
 * Sağlayıcıdan gelen abonelik sonucunu işler. İdempotent.
 *
 * Aynı bildirim iki kez gelebilir; durum sağlayıcının söylediğiyle
 * eşitleniyor, artırılmıyor — tekrar eden bildirim aynı sonucu üretir.
 */
export async function abonelikSonucunuIsle(token: string): Promise<{
  abonelikId: string | null;
  durum: AbonelikDurumu;
}> {
  const saglayici = odemeSaglayici();
  if (!abonelikDestekliyorMu(saglayici)) {
    return { abonelikId: null, durum: "bekliyor" };
  }

  const sonuc = await saglayici.abonelikSonucuAl(token);

  // Kayıt, başlatma sırasında saklanan geçici token ile bulunuyor.
  const [kayit] = await db
    .select()
    .from(subscriptions)
    .where(eq(subscriptions.providerRef, token))
    .limit(1);

  if (!kayit) return { abonelikId: null, durum: sonuc.durum };

  await db
    .update(subscriptions)
    .set({
      // Geçici token yerini kalıcı abonelik referansına bırakıyor.
      providerRef: sonuc.abonelikRef ?? kayit.providerRef,
      status: sonuc.durum,
      currentPeriodEnd: sonuc.donemSonu ? new Date(sonuc.donemSonu) : null,
    })
    .where(eq(subscriptions.id, kayit.id));

  return { abonelikId: kayit.id, durum: sonuc.durum };
}

/**
 * Aboneliği iptal eder.
 *
 * Erişim hemen kesilmiyor: ödenmiş dönemin sonuna kadar sürüyor, yoksa kullanan
 * kişi parasını ödediği süreyi kaybeder.
 */
export async function abonelikIptalEt(
  kullaniciId: string,
): Promise<{ ok: boolean; hata?: string }> {
  const saglayici = odemeSaglayici();
  if (!abonelikDestekliyorMu(saglayici)) {
    return { ok: false, hata: "Sağlayıcı aboneliği desteklemiyor." };
  }

  const kayit = await aktifAbonelik(kullaniciId);
  if (!kayit) return { ok: false, hata: "Aktif abonelik bulunamadı." };
  if (!kayit.providerRef) return { ok: false, hata: "Abonelik henüz tamamlanmamış." };

  const sonuc = await saglayici.abonelikIptal(kayit.providerRef);
  if (!sonuc.ok) return sonuc;

  /*
   * Durum `aktif` kalıyor, yalnızca `cancelAt` işaretleniyor.
   *
   * İptal erişimi anında kesmiyor: ödenmiş dönemin sonuna kadar sürüyor, yoksa
   * kullanan kişi parasını ödediği süreyi kaybeder. Durumu hemen "iptal"
   * yapmak aboneliği listeden de düşürüyordu ve kullanıcı ne zamana kadar
   * erişimi olduğunu göremiyordu.
   *
   * Dönem sonunda durumu sağlayıcı "iptal"e çeviriyor ve biz onu aynalıyoruz.
   */
  await db
    .update(subscriptions)
    .set({ cancelAt: new Date() })
    .where(eq(subscriptions.id, kayit.id));

  return { ok: true };
}
