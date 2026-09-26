import type { Metadata } from "next";

import { COZUMLER } from "@/data/cozumler";
import { KURUM } from "@/data/kurum";

/**
 * Sitenin sayfa listesi — **tek kaynak**.
 *
 * `sitemap.ts`, `robots.ts` ve kırıntı üretimi hep bunu okur. İki yerde tutulan
 * bir sayfa listesi kaçınılmaz olarak ayrışıyor: sitemap'e eklenmeyen yeni bir
 * sayfa ya da silindiği halde sitemap'te kalan bir adres kimseye hata vermez,
 * sessizce yanlış olur.
 */
export interface SayfaKaydi {
  readonly yol: string;
  readonly ad: string;
  /** Sitemap'e girsin mi. Giriş arkasındaki sayfalar girmez. */
  readonly sitemap: boolean;
  /** 0–1 arası; sitemap önceliği. */
  readonly oncelik: number;
  readonly degisim: "daily" | "weekly" | "monthly" | "yearly";
}

export const SAYFALAR: readonly SayfaKaydi[] = [
  { yol: "/", ad: "Ana sayfa", sitemap: true, oncelik: 1, degisim: "monthly" },
  { yol: "/platform", ad: "Platform", sitemap: true, oncelik: 0.9, degisim: "monthly" },
  { yol: "/platform/demo", ad: "Konsol demosu", sitemap: true, oncelik: 0.6, degisim: "monthly" },
  { yol: "/cozumler", ad: "Çözümler", sitemap: true, oncelik: 0.8, degisim: "monthly" },
  ...COZUMLER.map(
    (c): SayfaKaydi => ({
      yol: `/cozumler/${c.slug}`,
      ad: c.ad,
      sitemap: true,
      oncelik: 0.7,
      degisim: "monthly",
    }),
  ),
  { yol: "/teknoloji", ad: "Teknoloji", sitemap: true, oncelik: 0.8, degisim: "monthly" },
  { yol: "/fiyatlandirma", ad: "Fiyatlandırma", sitemap: true, oncelik: 0.8, degisim: "monthly" },
  { yol: "/hakkimizda", ad: "Hakkımızda", sitemap: true, oncelik: 0.6, degisim: "yearly" },
  { yol: "/hakkimizda/yonetim", ad: "Yönetim", sitemap: true, oncelik: 0.4, degisim: "yearly" },
  { yol: "/basin", ad: "Basın", sitemap: true, oncelik: 0.4, degisim: "yearly" },
  { yol: "/iletisim", ad: "İletişim", sitemap: true, oncelik: 0.7, degisim: "yearly" },
  { yol: "/kvkk", ad: "KVKK aydınlatma metni", sitemap: true, oncelik: 0.2, degisim: "yearly" },
  { yol: "/gizlilik", ad: "Gizlilik politikası", sitemap: true, oncelik: 0.2, degisim: "yearly" },
  { yol: "/cerez", ad: "Çerez politikası", sitemap: true, oncelik: 0.2, degisim: "yearly" },
  { yol: "/kosullar", ad: "Kullanım koşulları", sitemap: true, oncelik: 0.2, degisim: "yearly" },
  { yol: "/mesafeli-satis", ad: "Mesafeli satış sözleşmesi", sitemap: true, oncelik: 0.2, degisim: "yearly" },
  { yol: "/iade", ad: "Teslimat ve iade koşulları", sitemap: true, oncelik: 0.2, degisim: "yearly" },

  // Giriş arkasındakiler: listede var ama sitemap dışı.
  { yol: "/panel", ad: "Panel", sitemap: false, oncelik: 0, degisim: "daily" },
];

/** Yolu mutlak adrese çevirir. */
export function mutlakAdres(yol: string): string {
  // Ana sayfanın canonical'ı sonunda eğik çizgi taşımaz: "/" ile "" iki ayrı
  // adres gibi dizinlenip aynı sayfayı ikiye bölüyor.
  return yol === "/" ? KURUM.siteUrl : `${KURUM.siteUrl}${yol}`;
}

export function sayfaMetadata(girdi: {
  baslik: string;
  aciklama: string;
  yol: string;
  /** Varsayılan true. Giriş arkasındaki sayfalarda false verilir. */
  dizinleme?: boolean;
}): Metadata {
  const { baslik, aciklama, yol, dizinleme = true } = girdi;
  const adres = mutlakAdres(yol);

  return {
    title: baslik,
    description: aciklama,
    alternates: { canonical: adres },
    robots: dizinleme ? undefined : { index: false, follow: false },
    openGraph: {
      type: "website",
      locale: "tr_TR",
      siteName: KURUM.kisaAd,
      title: `${baslik} — ${KURUM.kisaAd}`,
      description: aciklama,
      url: adres,
    },
    twitter: {
      card: "summary_large_image",
      title: `${baslik} — ${KURUM.kisaAd}`,
      description: aciklama,
    },
  };
}

export function organizationJsonLd(): Record<string, unknown> {
  return {
    "@context": "https://schema.org",
    "@type": "Organization",
    name: KURUM.kisaAd,
    legalName: KURUM.unvan,
    url: KURUM.siteUrl,
    email: KURUM.eposta,
    description:
      "Konuşana ve görünen kişiye dönen sosyal robot platformu geliştiriyoruz.",
    sameAs: [KURUM.repoUrl],
  };
}

export function productJsonLd(): Record<string, unknown> {
  return {
    "@context": "https://schema.org",
    "@type": "Product",
    name: "ASTRO V1",
    category: "Sosyal robot platformu",
    description:
      "Çevresindeki insanları gören, duyan ve kiminle ilgileneceğine kendi karar " +
      "veren robot platformu.",
    url: mutlakAdres("/platform"),
    brand: { "@type": "Brand", name: KURUM.kisaAd },
    /*
     * Fiyat bilgisi bilerek yok: tutarlar geliştirme değeri (R4) ve yapılandırılmış
     * veride uydurma fiyat yayımlamak arama sonuçlarında yanlış bilgi demek.
     */
  };
}

export function breadcrumbJsonLd(
  parcalar: ReadonlyArray<{ ad: string; yol: string }>,
): { "@context": string; "@type": string; itemListElement: Array<{ "@type": string; position: number; name: string; item: string }> } {
  return {
    "@context": "https://schema.org",
    "@type": "BreadcrumbList",
    itemListElement: parcalar.map((p, i) => ({
      "@type": "ListItem",
      position: i + 1,
      name: p.ad,
      item: mutlakAdres(p.yol),
    })),
  };
}

export function faqJsonLd(
  sorular: ReadonlyArray<{ soru: string; cevap: string }>,
): Record<string, unknown> {
  return {
    "@context": "https://schema.org",
    "@type": "FAQPage",
    mainEntity: sorular.map((s) => ({
      "@type": "Question",
      name: s.soru,
      acceptedAnswer: { "@type": "Answer", text: s.cevap },
    })),
  };
}
