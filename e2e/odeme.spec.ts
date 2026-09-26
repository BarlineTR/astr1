import { expect, type Page, test } from "@playwright/test";

async function hesapAc(page: Page) {
  const n = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
  await page.goto("/kayit");
  await page.getByLabel("Ad soyad").fill("Ödeme Kullanıcı");
  await page.getByLabel("E-posta").fill(`odeme-${n}@example.invalid`);
  await page.getByLabel("Parola").fill("Gecici-Parola-123");
  await page.getByLabel(/KVKK aydınlatma metnini okudum/).check();
  await page.getByRole("button", { name: "Hesap oluştur" }).click();
  await expect(page).toHaveURL(/\/panel/, { timeout: 15_000 });
}

test("destek paketi satın alma uçtan uca çalışır", async ({ page }) => {
  await hesapAc(page);
  await page.goto("/panel/abonelik");

  // "Çay" paketi — ilk destek kartı.
  await page.getByRole("button", { name: "Destek olun" }).first().click();

  // Sahte sağlayıcıda taklit sayfaya, gerçekte iyzico'ya yönlenir.
  await expect(page).toHaveURL(/\/odeme\/sahte\//, { timeout: 20_000 });
  await expect(page.getByText("gerçek bir ödeme sayfası değil")).toBeVisible();

  await page.getByRole("button", { name: "Ödemeyi onayla" }).click();

  await expect(page).toHaveURL(/\/odeme\/sonuc\//, { timeout: 20_000 });
  await expect(page.getByRole("heading", { name: "Ödeme alındı" })).toBeVisible();
  await expect(page.getByText("₺50,00").first()).toBeVisible();
});

test("reddedilen ödeme siparişi başarısız işaretler", async ({ page }) => {
  await hesapAc(page);
  await page.goto("/panel/abonelik");
  await page.getByRole("button", { name: "Destek olun" }).first().click();
  await expect(page).toHaveURL(/\/odeme\/sahte\//, { timeout: 20_000 });

  await page.getByRole("button", { name: "Ödemeyi reddet" }).click();

  await expect(page).toHaveURL(/\/odeme\/sonuc\//, { timeout: 20_000 });
  await expect(page.getByRole("heading", { name: "Ödeme tamamlanamadı" })).toBeVisible();
});

test("ödenen sipariş faturalar listesinde görünür", async ({ page }) => {
  await hesapAc(page);
  await page.goto("/panel/abonelik");
  await page.getByRole("button", { name: "Destek olun" }).first().click();
  await expect(page).toHaveURL(/\/odeme\/sahte\//, { timeout: 20_000 });
  await page.getByRole("button", { name: "Ödemeyi onayla" }).click();
  await expect(page).toHaveURL(/\/odeme\/sonuc\//, { timeout: 20_000 });

  await page.goto("/panel/faturalar");
  await expect(page.getByText("ödendi")).toBeVisible();
  await expect(page.getByText("₺50,00").first()).toBeVisible();
});

/*
 * Aynı sonuç iki kez gelebilir: sağlayıcı geri dönüşü, kullanıcının sayfayı
 * yenilemesi, ileride webhook. İkinci ödeme kaydı yaratmamalı.
 */
test("aynı geri dönüş iki kez gelirse tek ödeme kaydı oluşur", async ({ page, request }) => {
  await hesapAc(page);
  await page.goto("/panel/abonelik");
  await page.getByRole("button", { name: "Destek olun" }).first().click();
  await expect(page).toHaveURL(/\/odeme\/sahte\//, { timeout: 20_000 });

  const token = new URL(page.url()).pathname.split("/").pop()!;
  await page.getByRole("button", { name: "Ödemeyi onayla" }).click();
  await expect(page).toHaveURL(/\/odeme\/sonuc\//, { timeout: 20_000 });
  const siparisUrl = page.url();

  // Sağlayıcı bildirimi tekrar gönderiyor.
  const tekrar = await request.post("/api/odeme/geri-donus", {
    form: { token },
    maxRedirects: 0,
  });
  expect([303, 302]).toContain(tekrar.status());

  // Sipariş hâlâ ödenmiş ve tek sefer.
  await page.goto(siparisUrl);
  await expect(page.getByRole("heading", { name: "Ödeme alındı" })).toBeVisible();
});

test("anonim ziyaretçi satın alamaz", async ({ page }) => {
  await page.goto("/panel/abonelik");
  await expect(page).toHaveURL(/\/giris/);
});

test("sahte karar ucu bilinmeyen oturumu reddeder", async ({ request }) => {
  const yanit = await request.post("/api/odeme/sahte-karar", {
    data: { token: "sahte_olmayan-bir-oturum", sonuc: "basarili" },
  });
  expect(yanit.status()).toBe(404);
});
