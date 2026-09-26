import { expect, test } from "@playwright/test";

import { hesapAc, odemeEkraniniGec } from "./yardimcilar/odeme";

test("destek paketi satın alma uçtan uca çalışır", async ({ page }) => {
  await hesapAc(page, "odeme");
  await page.goto("/panel/abonelik");

  // "Çay" paketi — ilk destek kartı.
  await page.getByRole("button", { name: "Destek olun" }).first().click();

  // Sahte sağlayıcıda taklit sayfaya, gerçekte iyzico'ya yönlenir.
  await expect(page).toHaveURL(/\/odeme\/sahte\//, { timeout: 20_000 });
  await expect(page.getByText("gerçek bir ödeme sayfası değil")).toBeVisible();

  await odemeEkraniniGec(page, true);

  await expect(page).toHaveURL(/\/odeme\/sonuc\//, { timeout: 20_000 });
  await expect(page.getByRole("heading", { name: "Ödeme alındı" })).toBeVisible();
  await expect(page.getByText("₺50,00").first()).toBeVisible();
});

test("reddedilen ödeme siparişi başarısız işaretler", async ({ page }) => {
  await hesapAc(page, "odeme");
  await page.goto("/panel/abonelik");
  await page.getByRole("button", { name: "Destek olun" }).first().click();
  await expect(page).toHaveURL(/\/odeme\/sahte\//, { timeout: 20_000 });

  await odemeEkraniniGec(page, false);

  await expect(page).toHaveURL(/\/odeme\/sonuc\//, { timeout: 20_000 });
  await expect(page.getByRole("heading", { name: "Ödeme tamamlanamadı" })).toBeVisible();
});

test("ödenen sipariş faturalar listesinde görünür", async ({ page }) => {
  await hesapAc(page, "odeme");
  await page.goto("/panel/abonelik");
  await page.getByRole("button", { name: "Destek olun" }).first().click();
  await expect(page).toHaveURL(/\/odeme\/sahte\//, { timeout: 20_000 });
  await odemeEkraniniGec(page, true);
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
  await hesapAc(page, "odeme");
  await page.goto("/panel/abonelik");
  await page.getByRole("button", { name: "Destek olun" }).first().click();
  await expect(page).toHaveURL(/\/odeme\/sahte\//, { timeout: 20_000 });

  const token = new URL(page.url()).pathname.split("/").pop()!;
  await odemeEkraniniGec(page, true);
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
