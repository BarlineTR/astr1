import { expect, test } from "@playwright/test";

test("iletişim formu talebi kaydeder ve teşekkür gösterir", async ({ page }) => {
  await page.goto("/iletisim");

  await page.getByLabel("Ad soyad").first().fill("Ada Lovelace");
  await page.getByLabel("E-posta").first().fill(`ada-${Date.now()}@example.invalid`);
  await page
    .getByLabel("Mesajınız")
    .first()
    .fill("Platform hakkında bilgi almak istiyorum, bir demo mümkün mü?");
  await page.getByLabel(/KVKK aydınlatma metnini okudum/).first().check();
  await page.getByRole("button", { name: "Gönderin" }).click();

  await expect(page.getByText("Talebiniz alındı")).toBeVisible({ timeout: 15_000 });
});

test("KVKK onayı olmadan gönderilemez", async ({ page }) => {
  await page.goto("/iletisim");

  await page.getByLabel("Ad soyad").first().fill("Ada Lovelace");
  await page.getByLabel("E-posta").first().fill(`ada-${Date.now()}@example.invalid`);
  await page.getByLabel("Mesajınız").first().fill("Bu mesaj yeterince uzun bir mesajdır.");
  // Onay kutusu işaretlenmiyor.
  await page.getByRole("button", { name: "Gönderin" }).click();

  await expect(page.locator(".form__hata").first()).toContainText("KVKK", {
    timeout: 15_000,
  });
});

test("teklif talebinde kurum adı zorunlu", async ({ page }) => {
  await page.goto("/iletisim");

  const teklif = page.locator("#teklif");
  await teklif.getByLabel("Ad soyad").fill("Ada Lovelace");
  await teklif.getByLabel("E-posta").fill(`ada-${Date.now()}@example.invalid`);
  await teklif.getByLabel("Mesajınız").fill("Beş robot için teklif almak istiyoruz.");
  await teklif.getByLabel(/KVKK aydınlatma metnini okudum/).check();
  await teklif.getByRole("button", { name: "Teklif isteyin" }).click();

  await expect(teklif.locator(".form__alan-hata").first()).toContainText("kurum adı", {
    timeout: 15_000,
  });
});

test("tuzak alan doluysa talep reddedilir", async ({ page }) => {
  await page.goto("/iletisim");

  await page.getByLabel("Ad soyad").first().fill("Bot");
  await page.getByLabel("E-posta").first().fill(`bot-${Date.now()}@example.invalid`);
  await page.getByLabel("Mesajınız").first().fill("Bu mesaj yeterince uzun bir mesajdır.");
  await page.getByLabel(/KVKK aydınlatma metnini okudum/).first().check();

  // Gerçek kullanıcının göremediği alan; yalnızca bir bot doldurur.
  await page.locator('input[name="website"]').first().fill("http://spam.example");
  await page.getByRole("button", { name: "Gönderin" }).click();

  await expect(page.getByText("Talebiniz alındı")).toHaveCount(0);
});
