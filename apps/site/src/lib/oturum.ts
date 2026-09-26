import { headers } from "next/headers";
import { redirect } from "next/navigation";

import { auth } from "./auth";
import { donusYolu } from "./yetki";

/**
 * Sunucu bileşenleri için oturum.
 *
 * Middleware yalnızca çerezin varlığına bakıyor; oturumun gerçekten geçerli
 * olduğu burada doğrulanıyor. Süresi geçmiş ya da iptal edilmiş bir çerezle
 * gelen istek bu noktada girişe düşer.
 */
export async function oturumAl() {
  return auth.api.getSession({ headers: await headers() });
}

export async function oturumGerekli(istenenYol = "/panel") {
  const oturum = await oturumAl();
  /*
   * typedRoutes derleme anında sabit adresleri doğruluyor; bu adres çalışma
   * zamanında oluşuyor ve güvenliği donusYolu sağlıyor (dış adres ve
   * protokolsüz biçim reddediliyor). Tip bu yüzden daraltılıyor.
   */
  if (!oturum) redirect(donusYolu(istenenYol) as Parameters<typeof redirect>[0]);
  return oturum;
}
