import { expect, test } from "@playwright/test";

async function hesapAc(page: import("@playwright/test").Page) {
  const n = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
  const k = {
    email: `panel-${n}@example.invalid`,
    password: "Gecici-Parola-123",
    name: "Panel Kullanıcı",
  };

  await page.goto("/kayit");
  await page.getByLabel("Ad soyad").fill(k.name);
  await page.getByLabel("E-posta").fill(k.email);
  await page.getByLabel("Parola").fill(k.password);
  await page.getByLabel(/KVKK aydınlatma metnini okudum/).check();
  await page.getByRole("button", { name: "Hesap oluştur" }).click();
  await expect(page).toHaveURL(/\/panel/, { timeout: 15_000 });
  return k;
}

test("panel gezinmesi dört bölüm taşır", async ({ page }) => {
  await hesapAc(page);

  const nav = page.locator(".pano__nav");
  for (const ad of ["Cihazlar", "Abonelik", "Faturalar", "Hesap"]) {
    await expect(nav.getByRole("link", { name: ad })).toHaveCount(1);
  }
});

test("robot eklenebiliyor ve eşleştirme kodu bir kez gösteriliyor", async ({ page }) => {
  await hesapAc(page);

  await page.getByRole("link", { name: "Robot ekle" }).click();
  await expect(page).toHaveURL(/\/panel\/cihaz\/ekle/);

  const seri = `ASTRO-TEST-${Date.now()}`;
  await page.getByLabel("Robot adı").fill("Karşılama robotu");
  await page.getByLabel("Seri numarası").fill(seri);
  await page.getByRole("button", { name: "Robotu ekle" }).click();

  // Kod yalnızca bu ekranda görünür; veritabanında yalnızca özeti durur.
  await expect(page.getByText("Eşleştirme kodu")).toBeVisible({ timeout: 15_000 });
  const kod = await page.locator(".eslestirme__kod").textContent();
  expect(kod?.trim().length).toBeGreaterThan(10);

  await page.getByRole("link", { name: "Cihazlara dön" }).click();
  await expect(page.getByText("Karşılama robotu")).toBeVisible();
  await expect(page.getByText(seri)).toBeVisible();
});

test("aynı seri numarası ikinci kez eklenemez", async ({ page }) => {
  await hesapAc(page);
  const seri = `ASTRO-TEKRAR-${Date.now()}`;

  for (const beklenen of ["kod", "hata"]) {
    await page.goto("/panel/cihaz/ekle");
    await page.getByLabel("Robot adı").fill("Tekrar");
    await page.getByLabel("Seri numarası").fill(seri);
    await page.getByRole("button", { name: "Robotu ekle" }).click();

    if (beklenen === "kod") {
      await expect(page.getByText("Eşleştirme kodu")).toBeVisible({ timeout: 15_000 });
    } else {
      // Next'in rota duyurucusu da role="alert" taşıyor; mesaja göre daraltılıyor.
      await expect(page.getByText("Bu seri numarası zaten kayıtlı.")).toBeVisible({
        timeout: 15_000,
      });
    }
  }
});

test("abonelik sayfası planları ve eksik olanı açıkça gösteriyor", async ({ page }) => {
  await hesapAc(page);
  await page.goto("/panel/abonelik");

  await expect(page.getByRole("heading", { name: "Abonelik" })).toBeVisible();
  await expect(page.getByText("Aktif planınız yok")).toBeVisible();

  // Planlar fiyatlandırma sayfasıyla aynı kaynaktan gelmeli.
  await expect(page.getByText("Gözlem")).toBeVisible();
  await expect(page.getByText("Operasyon")).toBeVisible();

  // Ödeme adımı neden çalışmadığını söylüyor; sessizce kırık düğme yok.
  await expect(page.getByText(/ödeme altyapısı/i).first()).toBeVisible();
});

test("faturalar sayfası boş durumu anlatıyor", async ({ page }) => {
  await hesapAc(page);
  await page.goto("/panel/faturalar");

  await expect(page.getByRole("heading", { name: "Faturalar" })).toBeVisible();
  await expect(page.getByText("Henüz fatura yok")).toBeVisible();
});
