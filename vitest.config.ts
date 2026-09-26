import { resolve } from "node:path";

import { defineConfig } from "vitest/config";

/**
 * Birim testleri.
 *
 * `e2e/` dışarıda: oradaki dosyalar Playwright'ın koşucusuna ait ve vitest
 * onları toplayınca `test.use()` çağrısında patlıyor. İki koşucu iki ayrı
 * komuttur — `npm test` ve `npm run e2e`.
 *
 * `@/` takma adı Next'in tsconfig `paths` ayarından geliyor ve vitest onu
 * kendiliğinden bilmiyor; burada aynısı tanımlanmazsa site modülleri testte
 * çözümlenemiyor.
 */
export default defineConfig({
  resolve: {
    alias: { "@": resolve(import.meta.dirname, "apps/site/src") },
  },
  test: {
    include: ["**/*.{test,spec}.ts"],
    exclude: ["**/node_modules/**", "**/dist/**", "**/.next/**", "e2e/**"],
  },
});
