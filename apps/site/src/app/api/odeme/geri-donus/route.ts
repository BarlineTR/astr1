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
    return yonlendir("/odeme/sonuc/bilinmiyor", istek);
  }

  const sonuc = await odemeSonucunuIsle(token);

  if (!sonuc.siparisId) return yonlendir("/odeme/sonuc/bilinmiyor", istek);
  return yonlendir(`/odeme/sonuc/${sonuc.siparisId}`, istek);
}

export async function GET(istek: Request) {
  const url = new URL(istek.url);
  const token = url.searchParams.get("token");

  if (!token) {
    return yonlendir("/odeme/sonuc/bilinmiyor", istek);
  }

  const sonuc = await odemeSonucunuIsle(token);

  if (!sonuc.siparisId) return yonlendir("/odeme/sonuc/bilinmiyor", istek);
  return yonlendir(`/odeme/sonuc/${sonuc.siparisId}`, istek);
}

/**
 * Sağlayıcı POST ile geliyor ama kullanıcıya bir sayfa göstermemiz gerekiyor.
 * 303, tarayıcının GET ile devam etmesini sağlar — 302 ile bazı tarayıcılar
 * POST'u tekrarlıyor.
 */
function yonlendir(yol: string, istek?: Request): NextResponse {
  let siteUrl = KURUM.siteUrl;
  if (istek) {
    const host = istek.headers.get("x-forwarded-host") || istek.headers.get("host");
    if (host) {
      const proto =
        istek.headers.get("x-forwarded-proto") ||
        (host.startsWith("localhost") || host.startsWith("127.") || host.startsWith("192.") || host.startsWith("10.")
          ? "http"
          : "https");
      siteUrl = `${proto}://${host}`;
    }
  }
  return NextResponse.redirect(`${siteUrl}${yol}`, 303);
}
