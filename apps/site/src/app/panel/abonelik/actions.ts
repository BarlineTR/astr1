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

  const slug = String(form.get("slug") ?? "");
  const kalem = [...DESTEK_PAKETLERI, ...PLANLAR].find((k) => k.slug === slug);
  if (!kalem) return { ok: false, hata: "Ürün bulunamadı." };

  const guestEmail = String(form.get("eposta") ?? "").trim();
  const guestAdSoyad = String(form.get("ad") ?? "").trim();

  let userId: string | null = null;
  let email = "";
  let ad = "Müşteri";
  let soyad = "-";

  if (oturum) {
    userId = oturum.user.id;
    email = oturum.user.email;
    const parcalar = oturum.user.name.trim().split(/\s+/);
    ad = parcalar[0] || "Müşteri";
    soyad = parcalar.slice(1).join(" ") || "-";
  } else if (guestEmail && guestEmail.includes("@")) {
    email = guestEmail;
    const parcalar = guestAdSoyad.split(/\s+/);
    ad = parcalar[0] || "Destekçi";
    soyad = parcalar.slice(1).join(" ") || "-";
  } else {
    redirect(`/giris?donus=/fiyatlandirma` as Parameters<typeof redirect>[0]);
  }

  // Aylık abonelik planı için kullanıcı hesabı zorunlu
  if (kalem.periyot === "ay" && !oturum) {
    redirect(`/giris?donus=/fiyatlandirma` as Parameters<typeof redirect>[0]);
  }

  const basliklar = await headers();
  const host = basliklar.get("x-forwarded-host") || basliklar.get("host") || "localhost:3000";
  const proto =
    basliklar.get("x-forwarded-proto") ||
    (host.startsWith("localhost") || host.startsWith("127.") || host.startsWith("192.") || host.startsWith("10.")
      ? "http"
      : "https");
  const siteUrl = `${proto}://${host}`;

  const rawIp = basliklar.get("x-forwarded-for")?.split(",")[0]?.trim() || basliklar.get("x-real-ip") || "127.0.0.1";
  const ip = rawIp.includes(":") ? "127.0.0.1" : rawIp;

  /*
   * Aylık plan tekrarlayan tahsilat: kart sağlayıcıda saklanıyor ve her dönem
   * o çekiyor. Tek seferlik ödeme akışından tamamen ayrı bir yol.
   */
  if (kalem.periyot === "ay" && userId) {
    const abonelik = await abonelikBaslat({
      kullaniciId: userId,
      eposta: email,
      ad,
      soyad,
      ip,
      planSlug: kalem.slug,
      siteUrl,
    });

    if (abonelik.ok && abonelik.odemeSayfasiUrl) {
      redirect(abonelik.odemeSayfasiUrl as Parameters<typeof redirect>[0]);
    }

    // Sağlayıcıda tekrarlayan abonelik API'si aktif değilse (örn. iyzico standart hesabı)
    // kullanıcıyı mağdur etmeyip doğrudan 1 aylık periyot siparişi başlatıyoruz:
    const sonuc = await siparisOlustur({
      kullaniciId: userId,
      eposta: email,
      tur: "abonelik",
      kalemler: [{ slug: kalem.slug, ad: kalem.ad, birimKurus: kalem.fiyatKurus, adet: 1 }],
      alici: { ad, soyad, ip },
      siteUrl,
    });

    if (!sonuc.ok || !sonuc.odemeSayfasiUrl) {
      return { ok: false, hata: sonuc.hata ?? "Ödeme başlatılamadı." };
    }

    redirect(sonuc.odemeSayfasiUrl as Parameters<typeof redirect>[0]);
  }

  const sonuc = await siparisOlustur({
    kullaniciId: userId,
    eposta: email,
    tur: "destek",
    kalemler: [{ slug: kalem.slug, ad: kalem.ad, birimKurus: kalem.fiyatKurus, adet: 1 }],
    alici: { ad, soyad, ip },
    siteUrl,
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
