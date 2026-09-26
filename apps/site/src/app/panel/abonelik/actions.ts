"use server";

import { revalidatePath } from "next/cache";
import { headers } from "next/headers";
import { redirect } from "next/navigation";

import { DESTEK_PAKETLERI, PLANLAR } from "@/data/fiyatlar";
import { abonelikBaslat, abonelikIptalEt } from "@/lib/odeme/abonelik";
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
  const ip = basliklar.get("x-forwarded-for")?.split(",")[0]?.trim() ?? "127.0.0.1";
  const [ad, ...kalan] = oturum.user.name.trim().split(/\s+/);

  /*
   * Aylık plan tekrarlayan tahsilat: kart sağlayıcıda saklanıyor ve her dönem
   * o çekiyor. Tek seferlik ödeme akışından tamamen ayrı bir yol.
   */
  if (kalem.periyot === "ay") {
    const abonelik = await abonelikBaslat({
      kullaniciId: oturum.user.id,
      eposta: oturum.user.email,
      ad: ad ?? "Müşteri",
      soyad: kalan.join(" ") || "-",
      ip,
      planSlug: kalem.slug,
      siteUrl: KURUM.siteUrl,
    });

    if (!abonelik.ok || !abonelik.odemeSayfasiUrl) {
      return { ok: false, hata: abonelik.hata ?? "Abonelik başlatılamadı." };
    }
    redirect(abonelik.odemeSayfasiUrl as Parameters<typeof redirect>[0]);
  }

  const sonuc = await siparisOlustur({
    kullaniciId: oturum.user.id,
    eposta: oturum.user.email,
    tur: "destek",
    kalemler: [{ slug: kalem.slug, ad: kalem.ad, birimKurus: kalem.fiyatKurus, adet: 1 }],
    alici: { ad: ad ?? "Müşteri", soyad: kalan.join(" ") || "-", ip },
    siteUrl: KURUM.siteUrl,
  });

  if (!sonuc.ok || !sonuc.odemeSayfasiUrl) {
    return { ok: false, hata: sonuc.hata ?? "Ödeme başlatılamadı." };
  }

  // redirect() NEXT_REDIRECT fırlatır; try/catch dışında olmalı.
  redirect(sonuc.odemeSayfasiUrl as Parameters<typeof redirect>[0]);
}

export interface IptalSonuc {
  ok: boolean;
  hata?: string;
}

/**
 * Aboneliği iptal eder.
 *
 * Erişim hemen kesilmiyor: ödenmiş dönemin sonuna kadar sürüyor, yoksa kullanan
 * kişi parasını ödediği süreyi kaybeder.
 */
export async function abonelikIptal(
  _onceki: IptalSonuc | null,
  _form: FormData,
): Promise<IptalSonuc> {
  const oturum = await oturumAl();
  if (!oturum) return { ok: false, hata: "Önce giriş yapmanız gerekiyor." };

  const sonuc = await abonelikIptalEt(oturum.user.id);
  if (!sonuc.ok) return sonuc;

  revalidatePath("/panel/abonelik");
  return { ok: true };
}
