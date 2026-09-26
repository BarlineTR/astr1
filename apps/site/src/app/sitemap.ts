import type { MetadataRoute } from "next";

import { SAYFALAR, mutlakAdres } from "@/lib/seo";

/**
 * Site haritası, `SAYFALAR` listesinden üretilir.
 *
 * Elle yazılmış bir sitemap, yeni sayfa eklendiğinde güncellenmediği için
 * sessizce eksik kalıyor. Tek kaynak olduğu sürece böyle bir boşluk oluşmaz.
 */
export default function sitemap(): MetadataRoute.Sitemap {
  const simdi = new Date();

  return SAYFALAR.filter((s) => s.sitemap).map((s) => ({
    url: mutlakAdres(s.yol),
    lastModified: simdi,
    changeFrequency: s.degisim,
    priority: s.oncelik,
  }));
}
