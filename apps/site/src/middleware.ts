import { getSessionCookie } from "better-auth/cookies";
import { NextResponse, type NextRequest } from "next/server";

import { donusYolu } from "@/lib/yetki";

/**
 * Panel kapısı.
 *
 * Burada yalnızca çerezin **varlığına** bakılır, geçerliliğine değil:
 * middleware'de veritabanına gitmek her panel isteğine bir sorgu ekliyor ve
 * süresi geçmiş bir çerez zaten sayfanın kendi sunucu bileşeninde
 * `oturumGerekli()` ile yakalanıyor. Bu, iki katmanlı bir kontrol — ucuz olanı
 * önde, kesin olanı arkada.
 */
export function middleware(istek: NextRequest) {
  const cerez = getSessionCookie(istek);
  if (cerez) return NextResponse.next();

  const url = istek.nextUrl.clone();
  const hedef = donusYolu(istek.nextUrl.pathname);
  url.pathname = "/giris";
  url.search = hedef.slice(hedef.indexOf("?"));
  return NextResponse.redirect(url);
}

export const config = {
  matcher: ["/panel/:path*"],
};
