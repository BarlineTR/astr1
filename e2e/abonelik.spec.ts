import { expect, test } from "@playwright/test";

import { hesapAc, odemeEkraniniGec } from "./yardimcilar/odeme";

test("taklit ödeme ekranı geçersiz kartı reddeder", async ({ page }) => {
  await hesapAc(page, "abone");
  await page.goto("/panel/abonelik");
  await page.getByRole("button", { name: "Planı seçin" }).first().click();
  await expect(page).toHaveURL(/\/odeme\/sahte-abonelik\//, { timeout: 20_000 });

  await page.getByLabel("Kart numarası").fill("1234567812345678");
  await page.getByLabel("Kart üzerindeki ad").fill("A");
  await page.getByLabel("Son kullanma").fill("0120");
  await page.getByLabel("CVC").fill("1");
  await page.getByRole("button", { name: /abone ol/ }).click();

  // 3D adımına geçmemeli; dört alan da hata vermeli.
  await expect(page.getByText("3D Secure doğrulaması")).toHaveCount(0);
  await expect(page.getByText("Kart numarası geçersiz.")).toBeVisible();
  await expect(page.getByText("AA/YY biçiminde ve gelecekte olmalı.")).toBeVisible();
});

test("abonelik başlatılır ve panelde aktif görünür", async ({ page }) => {
  await hesapAc(page, "abone");
  await page.goto("/panel/abonelik");

  await page.getByRole("button", { name: "Planı seçin" }).first().click();
  await expect(page).toHaveURL(/\/odeme\/sahte-abonelik\//, { timeout: 20_000 });
  await expect(page.getByText("aylık yenilenir")).toBeVisible();

  await odemeEkraniniGec(page, true);

  await expect(page).toHaveURL(/\/panel\/abonelik/, { timeout: 20_000 });
  await expect(page.getByText("aktif")).toBeVisible();
  await expect(page.getByText("Bir sonraki tahsilat:")).toBeVisible();
});

test("aktif abonelik varken ikinci plan seçilemez", async ({ page }) => {
  await hesapAc(page, "abone");
  await page.goto("/panel/abonelik");
  await page.getByRole("button", { name: "Planı seçin" }).first().click();
  await expect(page).toHaveURL(/\/odeme\/sahte-abonelik\//, { timeout: 20_000 });
  await odemeEkraniniGec(page, true);
  await expect(page).toHaveURL(/\/panel\/abonelik/, { timeout: 20_000 });

  // İki abonelik iki kez tahsilat demek.
  for (const dugme of await page.getByRole("button", { name: "Planı seçin" }).all()) {
    await expect(dugme).toBeDisabled();
  }
});

test("abonelik iptal edilince dönem sonuna kadar sürer", async ({ page }) => {
  await hesapAc(page, "abone");
  await page.goto("/panel/abonelik");
  await page.getByRole("button", { name: "Planı seçin" }).first().click();
  await expect(page).toHaveURL(/\/odeme\/sahte-abonelik\//, { timeout: 20_000 });
  await odemeEkraniniGec(page, true);
  await expect(page).toHaveURL(/\/panel\/abonelik/, { timeout: 20_000 });

  await page.getByRole("button", { name: "Aboneliği iptal et" }).click();

  await expect(page.getByText(/Erişiminiz/)).toBeVisible({ timeout: 15_000 });
  await expect(page.getByText("ödediğiniz dönem")).toBeVisible();
});

test("reddedilen abonelik ödemesi ödenmedi olarak görünür", async ({ page }) => {
  await hesapAc(page, "abone");
  await page.goto("/panel/abonelik");
  await page.getByRole("button", { name: "Planı seçin" }).first().click();
  await expect(page).toHaveURL(/\/odeme\/sahte-abonelik\//, { timeout: 20_000 });

  await odemeEkraniniGec(page, false);

  await expect(page).toHaveURL(/\/panel\/abonelik/, { timeout: 20_000 });
  await expect(page.getByText("Son tahsilat alınamadı")).toBeVisible();
});
