import { expect, test } from "@playwright/test";

/* Ham HTML ölçülüyor: içerik sunucudan gelmeli, tarayıcıdan değil. */
test.use({ javaScriptEnabled: false });

const SAYFALAR = [
  { yol: "/platform", baslik: "Platform" },
  { yol: "/cozumler", baslik: "Çözümler" },
  { yol: "/cozumler/karsilama", baslik: "Karşılama" },
  { yol: "/teknoloji", baslik: "Teknoloji" },
  { yol: "/fiyatlandirma", baslik: "Fiyatlandırma" },
  { yol: "/hakkimizda", baslik: "Hakkımızda" },
  { yol: "/hakkimizda/yonetim", baslik: "Yönetim" },
  { yol: "/basin", baslik: "Basın" },
] as const;

for (const sayfa of SAYFALAR) {
  test(`${sayfa.yol} ham HTML'de tek bir h1 taşır`, async ({ page }) => {
    const yanit = await page.goto(sayfa.yol);
    expect(yanit?.status()).toBe(200);

    const h1 = page.locator("h1");
    await expect(h1).toHaveCount(1);
    await expect(h1).toContainText(sayfa.baslik);
  });
}

test("platform sayfası ölçülmüş değerleri gerçek tablo olarak yayar", async ({ page }) => {
  await page.goto("/platform");

  /*
   * Gerçek <table> olması önemli: üretken arama araçları ve ekran okuyucular
   * tabloyu satır/sütun ilişkisiyle okur, ızgarayla çizilmiş bir kutu yığınını
   * okuyamaz.
   */
  const tablo = page.locator("table");
  await expect(tablo).toHaveCount(1);
  await expect(tablo).toContainText("±85°");
  await expect(tablo).toContainText("2,5882");
});

test("fiyatlandırma sayfası geliştirme fiyatı olduğunu söyler", async ({ page }) => {
  await page.goto("/fiyatlandirma");

  // Uydurma tutarla yayına çıkmak fark edilmeden mümkün olmasın.
  await expect(page.getByRole("status").first()).toContainText("geliştirme aşaması");
  await expect(page.getByText("₺").first()).toBeVisible();
});

test("yönetim sayfası uydurma isim yerine yakında diyor", async ({ page }) => {
  await page.goto("/hakkimizda/yonetim");
  await expect(page.getByText("yakında")).toBeVisible();
});

test("çözüm sayfaları sektör başına statik üretilir", async ({ page }) => {
  await page.goto("/cozumler");
  // Liste sayfası üç sektörün üçüne de bağlantı vermeli.
  for (const ad of ["Karşılama", "Bilgilendirme", "Eğitim"]) {
    await expect(page.getByRole("link", { name: ad })).toBeVisible();
  }
});

test("yer tutucu kurum bilgisi her sayfanın altında uyarı üretir", async ({ page }) => {
  await page.goto("/hakkimizda");
  await expect(page.getByText("kurum bilgileri yer tutucudur")).toBeVisible();
});
