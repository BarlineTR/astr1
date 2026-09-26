/**
 * Kuruş ile iyzico'nun beklediği ondalık dizgi arasındaki dönüşüm.
 *
 * Bizde para her zaman tam sayı kuruş. iyzico ise `"199.90"` gibi ondalık
 * **dizgi** istiyor ve iki kuralı var:
 *
 *  1. Sepet kalemlerinin toplamı `price` alanına **birebir** eşit olmalı;
 *     bir kuruşluk fark isteği tamamen reddettiriyor.
 *  2. Ondalık ayracı nokta. `toLocaleString` ya da Intl kullanmak, Türkçe
 *     yerelde virgül üretip isteği bozardı.
 */

/** Kuruşu iyzico'nun ondalık dizgisine çevirir: 19990 → "199.90". */
export function kurusuDizgiye(kurus: number): string {
  if (!Number.isInteger(kurus)) {
    throw new TypeError(`Tutar tam sayı kuruş olmalı, alınan: ${kurus}`);
  }
  if (kurus < 0) {
    throw new RangeError(`Tutar negatif olamaz: ${kurus}`);
  }

  const lira = Math.trunc(kurus / 100);
  const artan = kurus % 100;
  return `${lira}.${String(artan).padStart(2, "0")}`;
}

/** iyzico'nun döndürdüğü ondalık dizgiyi kuruşa çevirir: "199.9" → 19990. */
export function dizgidenKurusa(dizgi: string): number {
  const eslesme = /^(\d+)(?:\.(\d{1,2}))?$/.exec(dizgi.trim());
  if (!eslesme) {
    throw new TypeError(`Çözümlenemeyen tutar: ${dizgi}`);
  }
  const lira = Number(eslesme[1]);
  const kesir = (eslesme[2] ?? "").padEnd(2, "0");
  return lira * 100 + Number(kesir);
}

/**
 * Sepet kalemlerinin toplamı ile beyan edilen tutarın eşitliğini zorlar.
 *
 * iyzico bir kuruşluk farkta isteği reddediyor ve döndürdüğü hata kullanıcıya
 * gösterilemeyecek kadar genel. Hatayı burada yakalamak, "ödeme başlatılamadı"
 * diye bakakalmaktan iyi.
 */
export function sepetToplamiDogrula(
  kalemler: ReadonlyArray<{ birimKurus: number; adet: number }>,
  beyanKurus: number,
): void {
  const toplam = kalemler.reduce((t, k) => t + k.birimKurus * k.adet, 0);
  if (toplam !== beyanKurus) {
    throw new RangeError(
      `Sepet toplamı (${toplam}) beyan edilen tutara (${beyanKurus}) eşit değil.`,
    );
  }
}
