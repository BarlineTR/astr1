import { NextResponse } from "next/server";

import { KURUM } from "@/data/kurum";
import { abonelikSonucunuIsle } from "@/lib/odeme/abonelik";

/**
 * Abonelik sonucunun bildirildiği uç.
 *
 * Tek seferlik ödemedeki mantığın aynısı: sağlayıcı token gönderiyor, sonucu
 * biz kendi anahtarlarımızla soruyoruz. Sahte bir istek abonelik uyduramaz.
 */
export async function POST(istek: Request) {
  const form = await istek.formData().catch(() => null);
  const token = form?.get("token");

  if (typeof token !== "string" || token.length === 0) {
    return NextResponse.redirect(`${KURUM.siteUrl}/panel/abonelik`, 303);
  }

  await abonelikSonucunuIsle(token);
  return NextResponse.redirect(`${KURUM.siteUrl}/panel/abonelik`, 303);
}
