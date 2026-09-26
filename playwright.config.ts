import { defineConfig } from "@playwright/test";

/**
 * Uçtan uca testler **üretim çıktısına** karşı koşar.
 *
 * Geliştirme sunucusu bazı şeyleri farklı yapıyor (kaynak haritalar, sıcak
 * yenileme, farklı önbellekleme); SSR içeriğini orada ölçmek yalancı yeşil
 * üretebilir. Ölçmek istediğimiz şey ziyaretçinin gerçekten aldığı yanıt.
 */
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? "list" : [["list"]],
  use: { baseURL: "http://localhost:3000" },
  webServer: {
    command: "npm run build:site && npm run start:site",
    url: "http://localhost:3000",
    reuseExistingServer: !process.env.CI,
    timeout: 240_000,
  },
});
