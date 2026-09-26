import type { NextConfig } from "next";

const config: NextConfig = {
  /*
   * Tek VPS'e taşınabilirlik kararı (tasarım belgesi D4).
   *
   * Koşullu, çünkü `next start` standalone çıktıyla çalışmıyor: koşulsuz
   * açıldığında yerel üretim koşusu uyarı verip farklı bir sunucu istiyordu.
   * Docker derlemesi BUILD_STANDALONE=1 verir, yerel ve Vercel normal çıktıyı
   * kullanır — taşıma yolu yine ilk günden sınanabilir durumda kalır.
   */
  output: process.env.BUILD_STANDALONE === "1" ? "standalone" : undefined,

  /*
   * Çalışma alanı paketleri kaynak TypeScript olarak yayımlanıyor (derlenmiş
   * ikinci bir kopya tutulmuyor), bu yüzden Next onları kendisi derler.
   */
  transpilePackages: ["@astro/protocol", "@astro/ui"],

  typedRoutes: true,

  /*
   * iyzipay paketlenmez, çalışma anında require edilir.
   *
   * SDK kaynak sınıflarını `fs.readdirSync(__dirname + "/resources")` ile
   * dinamik yüklüyor; paketleyici bunu çözemiyor ve derleme "Can't resolve
   * .../resources/ <dynamic>" ile düşüyor.
   */
  serverExternalPackages: ["iyzipay"],
};

export default config;
