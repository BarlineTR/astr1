import { expect, test } from "@playwright/test";

/** Her koşu kendi kullanıcısını yaratır; testler birbirinin durumuna binmez. */
function testKullanicisi() {
  const n = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
  return {
    email: `test-${n}@example.invalid`,
    password: "Gecici-Parola-123",
    name: "Test Kullanıcı",
  };
}

test("anonim ziyaretçi panele giremez ve girişe yönlenir", async ({ page }) => {
  await page.goto("/panel");
  await expect(page).toHaveURL(/\/giris/);
});

test("kayıt, çıkış ve yeniden giriş çalışır", async ({ page }) => {
  const k = testKullanicisi();

  await page.goto("/kayit");
  await page.getByLabel("Ad soyad").fill(k.name);
  await page.getByLabel("E-posta").fill(k.email);
  await page.getByLabel("Parola", { exact: true }).fill(k.password);
  await page.getByLabel(/KVKK aydınlatma metnini okudum/).check();
  await page.getByRole("button", { name: "Hesap oluştur" }).click();

  await expect(page).toHaveURL(/\/panel/, { timeout: 15_000 });

  await page.getByRole("button", { name: "Çıkış" }).click();
  await expect(page).toHaveURL(/localhost:3000\/$|\/giris/, { timeout: 15_000 });

  // Çıkıştan sonra panel yine kapalı: oturum gerçekten sonlandı.
  await page.goto("/panel");
  await expect(page).toHaveURL(/\/giris/);

  await page.getByLabel("E-posta").fill(k.email);
  await page.getByLabel("Parola", { exact: true }).fill(k.password);
  await page.getByRole("button", { name: "Giriş yap" }).click();
  await expect(page).toHaveURL(/\/panel/, { timeout: 15_000 });
});

test("yanlış parola anlaşılır hata verir ve panele sokmaz", async ({ page }) => {
  const k = testKullanicisi();

  await page.goto("/giris");
  await page.getByLabel("E-posta").fill(k.email);
  await page.getByLabel("Parola", { exact: true }).fill("yanlis-parola");
  await page.getByRole("button", { name: "Giriş yap" }).click();

  // Next'in rota duyurucusu da role="alert" taşıyor; forma ait kutuya bakılıyor.
  await expect(page.locator(".form__hata")).toBeVisible({ timeout: 15_000 });
  await expect(page).not.toHaveURL(/\/panel/);
});

test("KVKK onayı verilmeden kayıt olunamaz", async ({ page }) => {
  const k = testKullanicisi();

  await page.goto("/kayit");
  await page.getByLabel("Ad soyad").fill(k.name);
  await page.getByLabel("E-posta").fill(k.email);
  await page.getByLabel("Parola", { exact: true }).fill(k.password);
  // Onay kutusu işaretlenmiyor.
  await page.getByRole("button", { name: "Hesap oluştur" }).click();

  await expect(page).not.toHaveURL(/\/panel/);
});

test("giriş ve kayıt sayfaları dizinlenmez", async ({ page }) => {
  for (const yol of ["/giris", "/kayit"]) {
    await page.goto(yol);
    await expect(page.locator('meta[name="robots"]')).toHaveAttribute(
      "content",
      /noindex/,
    );
  }
});

test("kayıt gövdesine konan rol yok sayılır", async ({ request }) => {
  const k = testKullanicisi();

  /*
   * Yetki yükseltme denemesi: `role` alanı better-auth'ta input:false olarak
   * tanımlı. Bu koruma olmasaydı kayıt gövdesine role:"admin" koyan biri
   * kendini yönetici yapardı.
   */
  const yanit = await request.post("/api/auth/sign-up/email", {
    data: { name: k.name, email: k.email, password: k.password, role: "admin" },
  });
  expect(yanit.status()).toBe(200);

  const govde = (await yanit.json()) as { user?: { role?: string } };
  expect(govde.user?.role ?? "customer").toBe("customer");
});
