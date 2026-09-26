import { NextResponse } from "next/server";

import { KURUM } from "@/data/kurum";
import { odemeSonucunuIsle } from "@/lib/odeme/siparis";

/**
 * Sağlayıcının sonucu bildirdiği uç.
 *
 * iyzico buraya **yalnızca token** POST ediyor; sonucu biz kendi
 * anahtarlarımızla ayrıca soruyoruz. Güvenin dayandığı yer bu: sahte bir geri
 * dönüş isteği başarılı bir ödeme uyduramaz, çünkü doğruyu sağlayıcının API'si
 * söylüyor.
 *
 * Durum burada kesinleşiyor, kullanıcının tarayıcısı geri dönsün diye değil:
 * sekmeyi kapatsa da sipariş tamamlanır.
 */
export async function POST(istek: Request) {
  const form = await istek.formData().catch(() => null);
  const token = form?.get("token");

  if (typeof token !== "string" || token.length === 0) {
    return yonlendir("/odeme/sonuc/bilinmiyor");
  }

  const sonuc = await odemeSonucunuIsle(token);

  if (!sonuc.siparisId) return yonlendir("/odeme/sonuc/bilinmiyor");
  return yonlendir(`/odeme/sonuc/${sonuc.siparisId}`);
}

/**
 * Sağlayıcı POST ile geliyor ama kullanıcıya bir sayfa göstermemiz gerekiyor.
 * 303, tarayıcının GET ile devam etmesini sağlar — 302 ile bazı tarayıcılar
 * POST'u tekrarlıyor.
 */
function yonlendir(yol: string): NextResponse {
  return NextResponse.redirect(`${KURUM.siteUrl}${yol}`, 303);
}
