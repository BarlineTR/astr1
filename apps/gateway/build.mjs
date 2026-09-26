/**
 * Ağ geçidini tek dosyaya paketler.
 *
 * Neden tsc değil: `tsc` göreli importları uzantısız bırakıyor ve Node ESM
 * bunları çözemiyor (`Cannot find module './command'`). Ayrıca `@astro/protocol`
 * kaynak TypeScript olarak yayımlanıyor — Node onu doğrudan çalıştıramaz.
 *
 * Neden her şey paketleniyor: çalışma imajı node_modules taşımasın. Tek dosya
 * 2,4 MB; bağımlılıklar dışarıda bırakıldığında imaj 1,14 GB oluyordu çünkü
 * npm çalışma alanı ağacını ağ geçidinin ihtiyacına göre budamıyor.
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
 * Dışarıda kalan tek şey `ws`in isteğe bağlı yerel hızlandırıcıları: bunlar
 * derlenmiş ikili dosyalar ve paketlenemezler. Yokluklarında `ws` saf JS
 * yoluna düşüyor.
 */
const external = ["bufferutil", "utf-8-validate"];

await build({
  entryPoints: [join(kok, "src/index.ts")],
  outfile: join(kok, "dist/index.js"),
  bundle: true,
  platform: "node",
  format: "esm",
  target: "node20",
  sourcemap: true,
  external,
  /*
   * Paketin içindeki CommonJS bağımlılıkları `require("node:http")` çağırıyor
   * ve ESM çıktısında `require` tanımlı değil: paket "Dynamic require of
   * node:http is not supported" ile açılmıyordu.
   */
  banner: {
    js: [
      'import { createRequire as __createRequire } from "node:module";',
      "const require = __createRequire(import.meta.url);",
    ].join("\n"),
  },
});
