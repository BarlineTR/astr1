import { describe, expect, it } from "vitest";

import { SAYFALAR, breadcrumbJsonLd, organizationJsonLd, sayfaMetadata } from "./seo";

describe("sayfaMetadata", () => {
  it("canonical adresi mutlak üretir", () => {
    const m = sayfaMetadata({ baslik: "Platform", aciklama: "x", yol: "/platform" });
    expect(m.alternates?.canonical).toMatch(/^https?:\/\/.+\/platform$/);
  });

  /* Ana sayfanın canonical'ı sonunda eğik çizgi taşımaz: iki adres tek sayfa demek. */
  it("ana sayfa canonical'ı çift adres üretmez", () => {
    const m = sayfaMetadata({ baslik: "ASTRO", aciklama: "x", yol: "/" });
    expect(String(m.alternates?.canonical)).not.toMatch(/.\/$/);
  });

  it("OG başlığı ve açıklaması doldurulur", () => {
    const m = sayfaMetadata({ baslik: "Teknoloji", aciklama: "ölçüm", yol: "/teknoloji" });
    expect(String(m.openGraph?.title)).toContain("Teknoloji");
    expect(m.openGraph?.description).toBe("ölçüm");
  });

  /* Giriş arkasındaki sayfa arama motoruna verilmez: işe yaramaz ve kapıyı ilan eder. */
  it("korunan sayfayı dizinlenmez işaretler", () => {
    const m = sayfaMetadata({ baslik: "Panel", aciklama: "x", yol: "/panel", dizinleme: false });
    expect(m.robots).toMatchObject({ index: false, follow: false });
  });
});

describe("SAYFALAR", () => {
  it("her kayıt tekil bir yol taşır", () => {
    const yollar = SAYFALAR.map((s) => s.yol);
    expect(new Set(yollar).size).toBe(yollar.length);
  });

  it("giriş arkasındaki sayfalar sitemap dışıdır", () => {
    for (const sayfa of SAYFALAR.filter((s) => s.sitemap)) {
      expect(sayfa.yol.startsWith("/panel")).toBe(false);
      expect(["/giris", "/kayit"]).not.toContain(sayfa.yol);
    }
  });

  it("ana sayfa en yüksek önceliği taşır", () => {
    const ana = SAYFALAR.find((s) => s.yol === "/");
    expect(ana?.oncelik).toBe(1);
  });
});

describe("organizationJsonLd", () => {
  it("şema tipini ve adı taşır", () => {
    const ld = organizationJsonLd();
    expect(ld["@type"]).toBe("Organization");
    expect(ld.name).toBeTruthy();
    expect(ld["@context"]).toBe("https://schema.org");
  });
});

describe("breadcrumbJsonLd", () => {
  it("sırayı 1'den başlatır", () => {
    const ld = breadcrumbJsonLd([
      { ad: "Ana sayfa", yol: "/" },
      { ad: "Platform", yol: "/platform" },
    ]);
    expect(ld.itemListElement[0]?.position).toBe(1);
    expect(ld.itemListElement[1]?.position).toBe(2);
  });

  it("öğe adreslerini mutlak verir", () => {
    const ld = breadcrumbJsonLd([{ ad: "Platform", yol: "/platform" }]);
    expect(ld.itemListElement[0]?.item).toMatch(/^https?:\/\//);
  });
});
