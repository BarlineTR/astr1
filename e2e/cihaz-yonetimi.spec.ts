import { expect, type Page, test } from "@playwright/test";

async function hesapAc(page: Page) {
  const n = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
  await page.goto("/kayit");
  await page.getByLabel("Ad soyad").fill("Cihaz Sahibi");
  await page.getByLabel("E-posta").fill(`cihaz-${n}@example.invalid`);
  await page.getByLabel("Parola").fill("Gecici-Parola-123");
  await page.getByLabel(/KVKK aydınlatma metnini okudum/).check();
  await page.getByRole("button", { name: "Hesap oluştur" }).click();
  await expect(page).toHaveURL(/\/panel/, { timeout: 15_000 });
}

async function robotEkle(page: Page, ad: string): Promise<string> {
  await page.goto("/panel/cihaz/ekle");
  await page.getByLabel("Robot adı").fill(ad);
  await page.getByLabel("Seri numarası").fill(`SR-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`);
  await page.getByRole("button", { name: "Robotu ekle" }).click();
  await expect(page.getByText("Eşleştirme kodu")).toBeVisible({ timeout: 15_000 });
  return (await page.locator(".eslestirme__kod").textContent())!.trim();
}

test("cihaz sayfasından eşleştirme kodu yenilenebiliyor", async ({ page }) => {
  await hesapAc(page);
  const ilkKod = await robotEkle(page, "Kod yenileme robotu");

  await page.getByRole("link", { name: "Cihazlara dön" }).click();
  await page.getByRole("link", { name: "Kod yenileme robotu" }).click();

  await page.getByRole("button", { name: "Kodu yenile" }).click();
  await expect(page.getByText("Eşleştirme kodu")).toBeVisible({ timeout: 15_000 });

  const yeniKod = (await page.locator(".eslestirme__kod").textContent())!.trim();
  expect(yeniKod).not.toBe(ilkKod);
  expect(yeniKod).toMatch(/^[A-Z2-9]{4}(-[A-Z2-9]{4}){3}$/);
});

test("cihaz silme onay ister ve seri numarası yazılmadan silmez", async ({ page }) => {
  await hesapAc(page);
  await robotEkle(page, "Silinecek robot");
  await page.getByRole("link", { name: "Cihazlara dön" }).click();
  await page.getByRole("link", { name: "Silinecek robot" }).click();

  const seri = (await page.locator(".cihaz-basligi__seri").textContent())!.trim();

  // Yanlış seri numarası: silme gerçekleşmemeli.
  await page.getByLabel(/Silmek için seri numarasını yazın/).fill("YANLIS-SERI");
  await page.getByRole("button", { name: "Cihazı sil" }).click();
  await expect(page.getByText("Seri numarası eşleşmiyor")).toBeVisible({ timeout: 15_000 });

  // Doğru seri numarası: silinir ve listeden düşer.
  await page.getByLabel(/Silmek için seri numarasını yazın/).fill(seri);
  await page.getByRole("button", { name: "Cihazı sil" }).click();

  await expect(page).toHaveURL(/\/panel$/, { timeout: 15_000 });
  await expect(page.getByText("Silinecek robot")).toHaveCount(0);
});

test("başkasının cihazını silmeye çalışmak 404 verir", async ({ page }) => {
  await hesapAc(page);
  await robotEkle(page, "Sahipli robot");
  await page.getByRole("link", { name: "Cihazlara dön" }).click();
  const url = await page.getByRole("link", { name: "Sahipli robot" }).getAttribute("href");

  // İkinci kullanıcı aynı adrese gidiyor.
  await page.getByRole("button", { name: "Çıkış" }).click();
  await hesapAc(page);

  const yanit = await page.goto(url!);
  expect(yanit?.status()).toBe(404);
});
