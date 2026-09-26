import { expect, test } from "@playwright/test";

test("robots.txt sitemap'i bildirir ve panel yolunu yasaklar", async ({ request }) => {
  const yanit = await request.get("/robots.txt");
  expect(yanit.status()).toBe(200);

  const govde = await yanit.text();
  expect(govde).toContain("Sitemap:");
  expect(govde).toContain("/sitemap.xml");
  // Giriş arkasındaki yollar dizine verilmez.
  expect(govde).toContain("/panel/");
  expect(govde).toContain("/giris");
  expect(govde).toContain("/api/");
});

test("sitemap.xml kurumsal sayfaları içerir, panele yer vermez", async ({ request }) => {
  const yanit = await request.get("/sitemap.xml");
  expect(yanit.status()).toBe(200);

  const govde = await yanit.text();
  for (const yol of ["/platform", "/cozumler/karsilama", "/teknoloji", "/fiyatlandirma"]) {
    expect(govde).toContain(yol);
  }
  expect(govde).not.toContain("<loc>http://localhost:3000/panel</loc>");
});

test("ana sayfa tek bir canonical ve geçerli Organization JSON-LD taşır", async ({ page }) => {
  await page.goto("/");

  const canonical = page.locator('link[rel="canonical"]');
  await expect(canonical).toHaveCount(1);
  // Ana sayfanın canonical'ı sonunda eğik çizgi taşımamalı: iki adres tek sayfa demek.
  const href = await canonical.getAttribute("href");
  expect(href).not.toMatch(/.\/$/);

  const ldler = await page.locator('script[type="application/ld+json"]').allTextContents();
  expect(ldler.length).toBeGreaterThanOrEqual(2);

  const cozulmus = ldler.map((x) => JSON.parse(x) as Record<string, unknown>);
  expect(cozulmus.some((x) => x["@type"] === "Organization")).toBe(true);
  expect(cozulmus.some((x) => x["@type"] === "Product")).toBe(true);
});

test("her kurumsal sayfa kendi canonical'ını ve OG başlığını taşır", async ({ page }) => {
  for (const yol of ["/platform", "/teknoloji", "/fiyatlandirma", "/hakkimizda"]) {
    await page.goto(yol);
    await expect(page.locator('link[rel="canonical"]')).toHaveAttribute(
      "href",
      new RegExp(`${yol}$`),
    );
    await expect(page.locator('meta[property="og:title"]')).toHaveAttribute(
      "content",
      /ASTRO$/,
    );
  }
});

test("paylaşım görseli üretiliyor", async ({ request }) => {
  const yanit = await request.get("/opengraph-image");
  expect(yanit.status()).toBe(200);
  expect(yanit.headers()["content-type"]).toContain("image/png");
});
