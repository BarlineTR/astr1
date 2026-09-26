import { expect, type Page } from "@playwright/test";

/**
 * Taklit ödeme ekranını geçer.
 *
 * Ekran gerçek bir ödeme sayfası gibi davranıyor: kart alanları, doğrulama ve
 * 3D Secure adımı. Testlerin bu yolu izlemesi önemli — kısa devre yapan bir
 * test, ekranın gerçekten çalıştığını göstermezdi.
 */
export async function odemeEkraniniGec(page: Page, onayla: boolean): Promise<void> {
  await page.getByLabel("Kart numarası").fill("5528790000000008");
  await page.getByLabel("Kart üzerindeki ad").fill("ADA LOVELACE");
  await page.getByLabel("Son kullanma").fill("1230");
  await page.getByLabel("CVC").fill("123");
  await page.getByRole("button", { name: /abone ol|öde$|öde\b/ }).click();

  await expect(page.getByText("3D Secure doğrulaması")).toBeVisible({ timeout: 15_000 });

  if (!onayla) {
    await page.getByRole("button", { name: "Ödemeyi reddet" }).click();
    return;
  }

  // Taklit ekranda kod sabit; sandbox'ta da öyle.
  await page.getByLabel("Doğrulama kodu").fill("123456");
  await page.getByRole("button", { name: "Onayla" }).click();
}

/** Yeni bir hesap açar ve panele girer. */
export async function hesapAc(page: Page, onek = "test"): Promise<void> {
  const n = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
  await page.goto("/kayit");
  await page.getByLabel("Ad soyad").fill("Test Kullanıcı");
  await page.getByLabel("E-posta").fill(`${onek}-${n}@example.invalid`);
  await page.getByLabel("Parola").fill("Gecici-Parola-123");
  await page.getByLabel(/KVKK aydınlatma metnini okudum/).check();
  await page.getByRole("button", { name: "Hesap oluştur" }).click();
  await expect(page).toHaveURL(/\/panel/, { timeout: 15_000 });
}
