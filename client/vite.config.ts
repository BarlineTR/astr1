import { resolve } from "node:path";
import { defineConfig } from "vite";

/**
 * Üç ayrı sayfa, üç ayrı giriş noktası.
 *
 * İstemci tarafı yönlendirme yok: her sayfa kendi HTML'i olarak üretilir. Statik
 * barındırmada (Vercel) doğrudan çalışır, yerel Fastify sunucusunda da aynı
 * dosyalar servis edilir.
 */
export default defineConfig({
  server: {
    port: 5173,
    proxy: {
      // Geliştirmede telemetri yerel Fastify sunucusundan gelir.
      "/ws": { target: "ws://localhost:8420", ws: true },
    },
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
    chunkSizeWarningLimit: 700,
    rollupOptions: {
      input: {
        index: resolve(import.meta.dirname, "index.html"),
        hakkimizda: resolve(import.meta.dirname, "hakkimizda.html"),
        konsol: resolve(import.meta.dirname, "konsol.html"),
      },
    },
  },
});
