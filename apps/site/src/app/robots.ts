import type { MetadataRoute } from "next";

import { KURUM } from "@/data/kurum";
import { SAYFALAR } from "@/lib/seo";

/**
 * Tarayıcı kuralları.
 *
 * Giriş arkasındaki yollar `SAYFALAR` listesinden türetilir; ayrıca API ve
 * kimlik yolları elle yasaklanır. Bunları dizine vermek hem işe yaramaz hem de
 * kapının nerede olduğunu ilan eder.
 */
export default function robots(): MetadataRoute.Robots {
  const korunan = SAYFALAR.filter((s) => !s.sitemap).map((s) => `${s.yol}/`);

  return {
    rules: {
      userAgent: "*",
      allow: "/",
      disallow: [...korunan, "/giris", "/kayit", "/api/"],
    },
    sitemap: `${KURUM.siteUrl}/sitemap.xml`,
    host: KURUM.siteUrl,
  };
}
