import { expect, test } from "@playwright/test";

test.use({ javaScriptEnabled: false });

const SAYFALAR = ["/kvkk", "/gizlilik", "/cerez", "/kosullar", "/mesafeli-satis", "/iade"];

for (const yol of SAYFALAR) {
  test(`${yol} açılır, taslak olduğunu söyler ve sürümünü gösterir`, async ({ page }) => {
    const yanit = await page.goto(yol);
    expect(yanit?.status()).toBe(200);

    // Onaysız bir metnin yayında olduğu gizlenmemeli.
    await expect(page.locator(".uyari-serit")).toContainText(
      "hukukçu onayından geçmemiştir",
    );

    // Onay kayıtları bu sürüme referans veriyor; görünmezse kullanıcı neyi
    // onayladığını sonradan bulamaz.
    await expect(page.getByText(/Sürüm: /)).toBeVisible();
  });
}

test("hukuki sayfalar sitemap'te yer alır", async ({ request }) => {
  const govde = await (await request.get("/sitemap.xml")).text();
  for (const yol of SAYFALAR) {
    expect(govde).toContain(yol);
  }
});
