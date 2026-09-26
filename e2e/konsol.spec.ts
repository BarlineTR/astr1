import { expect, test } from "@playwright/test";

test("genel demo simülasyon olduğunu açıkça söyler", async ({ page }) => {
  await page.goto("/platform/demo");

  await expect(page.getByText("SİMÜLASYON")).toBeVisible({ timeout: 15_000 });

  /*
   * Demo robota bağlanmaz: komut arayüzü devre dışı değil, hiç yok. Genel bir
   * sayfada düğmeyi kapatmak yetmez, yolun var olmaması gerekir.
   */
  await expect(page.getByRole("button", { name: /ACİL DURDURMA/ })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Merkeze al" })).toHaveCount(0);
  await expect(page.getByLabel("Kafa hedef açısı")).toHaveCount(0);
});

test("demo telemetri akıtıyor", async ({ page }) => {
  await page.goto("/platform/demo");

  // Senaryo sürücüsü çalışıyorsa ölçülen açı bir süre sonra "—" olmaktan çıkar.
  const olculen = page.locator(".readouts__value").nth(1);
  await expect(olculen).not.toHaveText("—", { timeout: 15_000 });
});

test("anonim ziyaretçi gerçek konsolu göremez", async ({ page }) => {
  await page.goto("/panel/cihaz/00000000-0000-0000-0000-000000000001");
  await expect(page).toHaveURL(/\/giris/);
});

/*
 * Yetkisiz kullanıcıya 403 değil 404 verilir: 403, o kimlikte bir cihazın
 * gerçekten var olduğunu söyler ve kimlikleri tarayarak envanter çıkarmaya
 * izin verir.
 */
test("başkasının cihazına erişim 404 döner, 403 değil", async ({ page }) => {
  const k = {
    email: `yabanci-${Date.now()}@example.invalid`,
    password: "Gecici-Parola-123",
    name: "Yabancı Kullanıcı",
  };

  await page.goto("/kayit");
  await page.getByLabel("Ad soyad").fill(k.name);
  await page.getByLabel("E-posta").fill(k.email);
  await page.getByLabel("Parola").fill(k.password);
  await page.getByLabel(/KVKK aydınlatma metnini okudum/).check();
  await page.getByRole("button", { name: "Hesap oluştur" }).click();
  await expect(page).toHaveURL(/\/panel/, { timeout: 15_000 });

  const yanit = await page.goto("/panel/cihaz/00000000-0000-0000-0000-000000000001");
  expect(yanit?.status()).toBe(404);
});
