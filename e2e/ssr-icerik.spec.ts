import { expect, test } from "@playwright/test";

/*
 * JavaScript kapalıyken ölçüyoruz.
 *
 * Taşımadan önceki hata JS açıkken hiç görünmüyordu: tarayıcı bütün içeriği
 * kendisi çiziyordu ve ham HTML gövdesi <div id="app"></div> idi. Arama motoru
 * tarayıcıları ve LLM tarayıcıları çoğu zaman JS çalıştırmaz, bu yüzden ölçüt
 * ham yanıtın kendisi.
 */
test.use({ javaScriptEnabled: false });

test("ana sayfa ham HTML'de başlığını ve gövde metnini taşır", async ({ page }) => {
  await page.goto("/");

  const h1 = page.locator("h1");
  await expect(h1).toHaveCount(1);
  await expect(h1).toContainText("Konuşanı duyar");

  // Gövde metni de sunucudan gelmeli, yalnızca başlık değil.
  await expect(page.getByText("kiminle ilgileneceğine kendi")).toBeVisible();
});

test("ana sayfa ölçülmüş çalışma sınırlarını metin olarak yayar", async ({ page }) => {
  await page.goto("/");

  // Bu değerler @astro/protocol sabitlerinden gelir, elle yazılmaz.
  await expect(page.getByText("±85°")).toBeVisible();
  await expect(page.getByText("121°")).toBeVisible();
});

test("dil ve renk şeması sunucudan bildirilir", async ({ page }) => {
  await page.goto("/");

  await expect(page.locator("html")).toHaveAttribute("lang", "tr");
  await expect(page.locator('meta[name="color-scheme"]')).toHaveAttribute("content", "dark");
});
