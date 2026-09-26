/**
 * Ağ geçidini tek dosyaya paketler.
 *
 * Neden tsc değil: `tsc` göreli importları uzantısız bırakıyor ve Node ESM
 * bunları çözemiyor (`Cannot find module './command'`). Ayrıca `@astro/protocol`
 * kaynak TypeScript olarak yayımlanıyor — Node onu doğrudan çalıştıramaz.
 * Paketleme ikisini birlikte çözüyor: çalışma alanı paketi içine gömülür,
 * node_modules bağımlılıkları dışarıda kalır.
 *
 * Tipler ayrıca `npm run typecheck` ile denetlenir; bu betiğin işi yalnızca
 * çalıştırılabilir çıktı üretmek.
 */
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { build } from "esbuild";

const kok = dirname(fileURLToPath(import.meta.url));
const paket = JSON.parse(readFileSync(join(kok, "package.json"), "utf8"));

/*
 * Çalışma alanı paketleri gömülür, gerçek bağımlılıklar dışarıda bırakılır:
 * fastify'ı paketin içine almak imajı büyütür ve yerel eklentilerini bozar.
 */
const external = Object.keys(paket.dependencies ?? {}).filter(
  (ad) => !ad.startsWith("@astro/"),
);

await build({
  entryPoints: [join(kok, "src/index.ts")],
  outfile: join(kok, "dist/index.js"),
  bundle: true,
  platform: "node",
  format: "esm",
  target: "node20",
  sourcemap: true,
  external,
});
