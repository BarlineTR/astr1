import { defineConfig } from "vitest/config";

/**
 * Birim testleri.
 *
 * `e2e/` dışarıda: oradaki dosyalar Playwright'ın koşucusuna ait ve vitest
 * onları toplayınca `test.use()` çağrısında patlıyor. İki koşucu iki ayrı
 * komuttur — `npm test` ve `npm run e2e`.
 */
export default defineConfig({
  test: {
    include: ["**/*.{test,spec}.ts"],
    exclude: ["**/node_modules/**", "**/dist/**", "**/.next/**", "e2e/**"],
  },
});
