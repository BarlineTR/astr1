import { expect, test } from "@playwright/test";

test.use({ javaScriptEnabled: false });

test("üst şeritte İletişim gezinmede, sağda Hesap ve Panel ayrı duruyor", async ({ page }) => {
  await page.goto("/");

  const serit = page.locator(".site-header");

  // İletişim artık bir gezinme bağlantısı, sağdaki eylemlerden biri değil.
  await expect(serit.locator(".site-nav").getByRole("link", { name: "İletişim" })).toHaveCount(1);

  // Sağda iki ayrı eylem: Hesap sade, Panel çerçeveli.
  await expect(serit.getByRole("link", { name: "Hesap" })).toHaveCount(1);
  await expect(serit.getByRole("link", { name: "Panel", exact: true })).toHaveCount(1);
});

test("Hesap ve Panel farklı adreslere gider", async ({ page }) => {
  await page.goto("/");
  const serit = page.locator(".site-header");

  await expect(serit.getByRole("link", { name: "Hesap" })).toHaveAttribute(
    "href",
    "/panel/hesap",
  );
  await expect(serit.getByRole("link", { name: "Panel", exact: true })).toHaveAttribute(
    "href",
    "/panel",
  );
});

test("anonim ziyaretçi Hesap'a tıklayınca girişe düşer", async ({ page }) => {
  await page.goto("/panel/hesap");
  await expect(page).toHaveURL(/\/giris/);
  // Girişten sonra istenen sayfaya dönebilmeli.
  expect(page.url()).toContain("devam=");
});
