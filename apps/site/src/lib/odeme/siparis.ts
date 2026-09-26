import { randomUUID } from "node:crypto";

import { eq } from "drizzle-orm";

import { db } from "@/db";
import { tekilIhlalMi } from "@/db/hata";
import { orderItems, orders, payments } from "@/db/schema";

import { odemeSaglayici } from "./index";
import type { OdemeSonucu, SepetKalemi } from "./saglayici";

export interface SiparisOlusturGirdi {
  kullaniciId: string | null;
  eposta: string;
  tur: "destek" | "abonelik";
  kalemler: readonly SepetKalemi[];
  alici: { ad: string; soyad: string; ip: string };
  siteUrl: string;
}

export interface SiparisOlusturSonuc {
  ok: boolean;
  siparisId?: string;
  odemeSayfasiUrl?: string;
  hata?: string;
}

/**
 * Sipariş oluşturur ve ödeme oturumu başlatır.
 *
 * Sipariş **sağlayıcıya gitmeden önce** yazılıyor: sağlayıcı çağrısı başarılı
 * olup yanıtı bize ulaşmadan koparsa, kullanıcı ödemiş ama bizde hiçbir kayıt
 * yok olurdu. Önce `bekliyor` yazıp sonra başlatmak, en kötü durumda ödenmemiş
 * bir sipariş satırı bırakır — bu onarılabilir bir durum.
 */
export async function siparisOlustur(
  girdi: SiparisOlusturGirdi,
): Promise<SiparisOlusturSonuc> {
  const saglayici = odemeSaglayici();
  const siparisId = randomUUID();
  const conversationId = `astro-${siparisId}`;
  const toplam = girdi.kalemler.reduce((t, k) => t + k.birimKurus * k.adet, 0);

  if (toplam <= 0) return { ok: false, hata: "Sepet boş." };

  await db.insert(orders).values({
    id: siparisId,
    userId: girdi.kullaniciId,
    email: girdi.eposta,
    kind: girdi.tur,
    status: "bekliyor",
    totalMinor: toplam,
    currency: "TRY",
    provider: saglayici.id,
    conversationId,
  });

  await db.insert(orderItems).values(
    girdi.kalemler.map((k) => ({
      id: randomUUID(),
      orderId: siparisId,
      productSlug: k.slug,
      // Ad ve fiyat siparişe kopyalanıyor: fiyat sonradan değişince eski
      // siparişin tutarı değişmemeli.
      name: k.ad,
      unitPriceMinor: k.birimKurus,
      quantity: k.adet,
    })),
  );

  const baslat = await saglayici.odemeBaslat({
    siparisId,
    conversationId,
    toplamKurus: toplam,
    paraBirimi: "TRY",
    kalemler: girdi.kalemler,
    alici: {
      id: girdi.kullaniciId ?? siparisId,
      ad: girdi.alici.ad,
      soyad: girdi.alici.soyad,
      eposta: girdi.eposta,
      ip: girdi.alici.ip,
    },
    geriDonusUrl: `${girdi.siteUrl}/api/odeme/geri-donus`,
    periyot: girdi.tur === "abonelik" ? "ay" : "tek",
  });

  if (!baslat.ok || !baslat.odemeSayfasiUrl) {
    await db
      .update(orders)
      .set({ status: "basarisiz" })
      .where(eq(orders.id, siparisId));
    return { ok: false, hata: baslat.hata ?? "Ödeme başlatılamadı." };
  }

  await db
    .update(orders)
    .set({ providerRef: baslat.token ?? null })
    .where(eq(orders.id, siparisId));

  return { ok: true, siparisId, odemeSayfasiUrl: baslat.odemeSayfasiUrl };
}

export interface SonucIsleSonuc {
  siparisId: string | null;
  durum: "odendi" | "basarisiz" | "bilinmiyor";
  hata?: string;
}

/**
 * Sağlayıcıdan gelen sonucu işler.
 *
 * **İdempotent.** Aynı sonuç iki kez gelebilir: iyzico geri dönüşü, kullanıcının
 * sayfayı yenilemesi, ileride webhook. İkinci ödeme kaydı yaratmamalı ve
 * siparişi iki kez "ödendi" saymamalı.
 *
 * Tekillik veritabanında zorlanıyor (`payments.provider_payment_id`), kodda
 * "önce bak sonra yaz" ile değil: iki istek aynı anda geldiğinde o kontrol
 * ikisini de geçiriyordu.
 */
export async function odemeSonucunuIsle(token: string): Promise<SonucIsleSonuc> {
  const saglayici = odemeSaglayici();
  const sonuc: OdemeSonucu = await saglayici.sonucuAl(token);

  if (!sonuc.ok || !sonuc.conversationId) {
    return { siparisId: null, durum: "bilinmiyor", hata: sonuc.hata };
  }

  const [siparis] = await db
    .select()
    .from(orders)
    .where(eq(orders.conversationId, sonuc.conversationId))
    .limit(1);

  if (!siparis) {
    return { siparisId: null, durum: "bilinmiyor", hata: "Sipariş bulunamadı." };
  }

  /*
   * Tutar sağlayıcının söylediğiyle bizim beklediğimiz tutmalı. Tutmuyorsa
   * ödeme başarılı sayılmaz: farkı sessizce kabul etmek, eksik ödenmiş bir
   * siparişi tamamlanmış göstermek demek.
   */
  if (
    sonuc.durum === "basarili" &&
    sonuc.tutarKurus !== undefined &&
    sonuc.tutarKurus !== siparis.totalMinor
  ) {
    await db
      .update(orders)
      .set({ status: "basarisiz" })
      .where(eq(orders.id, siparis.id));
    return {
      siparisId: siparis.id,
      durum: "basarisiz",
      hata: "Ödenen tutar sipariş tutarıyla uyuşmuyor.",
    };
  }

  if (sonuc.odemeId) {
    try {
      await db.insert(payments).values({
        id: randomUUID(),
        orderId: siparis.id,
        provider: saglayici.id,
        providerPaymentId: sonuc.odemeId,
        status: sonuc.durum === "basarili" ? "basarili" : "basarisiz",
        amountMinor: sonuc.tutarKurus ?? siparis.totalMinor,
        currency: sonuc.paraBirimi ?? siparis.currency,
        cardFamily: sonuc.kartAilesi ?? null,
        cardLastFour: sonuc.kartSonDort ?? null,
        raw: sonuc.ham as Record<string, unknown>,
      });
    } catch (hata) {
      // Aynı ödeme ikinci kez geldi: kayıt zaten var, durum da zaten işlendi.
      if (!tekilIhlalMi(hata, "payments_provider_payment_id_unique")) throw hata;
    }
  }

  const yeniDurum = sonuc.durum === "basarili" ? "odendi" : "basarisiz";

  // Ödenmiş bir sipariş geri alınmaz: geç gelen bir "başarısız" bildirimi
  // tamamlanmış siparişi bozmamalı.
  if (siparis.status !== "odendi") {
    await db
      .update(orders)
      .set({
        status: yeniDurum,
        paidAt: yeniDurum === "odendi" ? new Date() : null,
      })
      .where(eq(orders.id, siparis.id));
  }

  return { siparisId: siparis.id, durum: yeniDurum };
}
