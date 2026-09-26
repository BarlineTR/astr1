import type { Rol } from "@/db/schema";

/** Panel yolları — korunan alan. */
export function panelYoluMu(yol: string): boolean {
  // Tam segment karşılaştırması: "/panelist" panel değildir ve önek
  // karşılaştırması onu yanlışlıkla korunan alana sokardı.
  return yol === "/panel" || yol.startsWith("/panel/");
}

/**
 * Girişten sonra dönülecek yol.
 *
 * Yalnızca tek eğik çizgiyle başlayan, ikinci karakteri eğik çizgi olmayan
 * yollar kabul edilir. `?devam=https://kotu.example` ve `?devam=//kotu.example`
 * açık yönlendirme açığıydı: kullanıcı bizim adresimizde giriş yapıp başka bir
 * siteye düşerdi.
 */
export function guvenliDonusYolu(devam: string | null | undefined): string {
  if (!devam) return "/panel";
  if (!devam.startsWith("/")) return "/panel";
  if (devam.startsWith("//")) return "/panel";
  // Ters eğik çizgi bazı tarayıcılarda eğik çizgi gibi çözümleniyor.
  if (devam.startsWith("/\\")) return "/panel";
  return devam;
}

/** Girişe yönlendirme adresi; istenen sayfa kodlanmış olarak taşınır. */
export function donusYolu(istenen: string): string {
  const hedef = guvenliDonusYolu(istenen);
  return `/giris?devam=${encodeURIComponent(hedef)}`;
}

export function yoneticiMi(kullanici: { role: Rol | string }): boolean {
  return kullanici.role === "admin";
}

export function operatorMu(kullanici: { role: Rol | string }): boolean {
  return kullanici.role === "admin" || kullanici.role === "operator";
}
