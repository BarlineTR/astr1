"use server";

import { headers } from "next/headers";
import { redirect } from "next/navigation";

import { DESTEK_PAKETLERI, PLANLAR } from "@/data/fiyatlar";
import { KURUM } from "@/data/kurum";
import { siparisOlustur } from "@/lib/odeme/siparis";
import { oturumAl } from "@/lib/oturum";

export interface SatinAlSonuc {
  ok: boolean;
  hata?: string;
}

/**
 * Satın alma başlatır ve kullanıcıyı ödeme sayfasına yönlendirir.
 *
 * Ürün ve fiyat **istemciden gelmiyor**: yalnızca slug geliyor, tutar sunucudaki
 * listeden okunuyor. Fiyatı istemcinin göndermesi, tutarı değiştirip bir
 * kuruşa satın almaya izin verirdi.
 */
export async function satinAl(
  _onceki: SatinAlSonuc | null,
  form: FormData,
): Promise<SatinAlSonuc> {
  const oturum = await oturumAl();
  if (!oturum) return { ok: false, hata: "Önce giriş yapmanız gerekiyor." };

  const slug = String(form.get("slug") ?? "");
  const kalem = [...DESTEK_PAKETLERI, ...PLANLAR].find((k) => k.slug === slug);
  if (!kalem) return { ok: false, hata: "Ürün bulunamadı." };

  const basliklar = await headers();
  const [ad, ...kalan] = oturum.user.name.trim().split(/\s+/);

  const sonuc = await siparisOlustur({
    kullaniciId: oturum.user.id,
    eposta: oturum.user.email,
    tur: kalem.periyot === "ay" ? "abonelik" : "destek",
    kalemler: [{ slug: kalem.slug, ad: kalem.ad, birimKurus: kalem.fiyatKurus, adet: 1 }],
    alici: {
      ad: ad ?? "Müşteri",
      soyad: kalan.join(" ") || "-",
      ip: basliklar.get("x-forwarded-for")?.split(",")[0]?.trim() ?? "127.0.0.1",
    },
    siteUrl: KURUM.siteUrl,
  });

  if (!sonuc.ok || !sonuc.odemeSayfasiUrl) {
    return { ok: false, hata: sonuc.hata ?? "Ödeme başlatılamadı." };
  }

  // redirect() NEXT_REDIRECT fırlatır; try/catch dışında olmalı.
  redirect(sonuc.odemeSayfasiUrl as Parameters<typeof redirect>[0]);
}
