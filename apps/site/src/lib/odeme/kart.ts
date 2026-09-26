/**
 * Kart alanı doğrulamaları — **yalnızca taklit ödeme ekranı için**.
 *
 * Gerçek akışta kart bilgisi bizim sunucumuza hiç uğramaz; iyzico kendi
 * sayfasında topluyor. Bu modül, anahtar yokken çalışan geliştirme ekranının
 * gerçekçi davranması için var: alan doğrulaması olmayan bir taklit, gerçek
 * ekranda karşılaşılacak hataları göstermez.
 */

/** Luhn denetimi — kart numaralarının standart sağlama yöntemi. */
export function luhnGecerliMi(numara: string): boolean {
  const rakamlar = numara.replace(/\D/g, "");
  if (rakamlar.length < 12 || rakamlar.length > 19) return false;

  let toplam = 0;
  let ikile = false;
  for (let i = rakamlar.length - 1; i >= 0; i--) {
    let d = Number(rakamlar[i]);
    if (ikile) {
      d *= 2;
      if (d > 9) d -= 9;
    }
    toplam += d;
    ikile = !ikile;
  }
  return toplam % 10 === 0;
}

/** Kart numarasını dörtlü gruplar hâlinde biçimler. */
export function kartNumarasiBicimle(ham: string): string {
  return ham
    .replace(/\D/g, "")
    .slice(0, 19)
    .replace(/(\d{4})(?=\d)/g, "$1 ")
    .trim();
}

/** AA/YY biçimindeki son kullanma tarihi geçerli ve gelecekte mi. */
export function sonKullanmaGecerliMi(deger: string, simdi = new Date()): boolean {
  const eslesme = /^(\d{2})\s*\/\s*(\d{2})$/.exec(deger.trim());
  if (!eslesme) return false;

  const ay = Number(eslesme[1]);
  const yil = 2000 + Number(eslesme[2]);
  if (ay < 1 || ay > 12) return false;

  // Ayın son gününe kadar geçerli: 12/26 kartı 31 Aralık 2026'da hâlâ geçerli.
  const sonGun = new Date(yil, ay, 0, 23, 59, 59);
  return sonGun >= simdi;
}

export function cvcGecerliMi(deger: string): boolean {
  return /^\d{3,4}$/.test(deger.trim());
}

/**
 * Kart ailesini numaradan tahmin eder.
 *
 * Yalnızca görsel: gerçek akışta bu bilgi sağlayıcıdan geliyor. Taklit ekranda
 * kart tipini göstermek, gerçek ekranın davranışını taklit etmek için.
 */
export function kartAilesi(numara: string): string | null {
  const r = numara.replace(/\D/g, "");
  if (/^4/.test(r)) return "Visa";
  if (/^(5[1-5]|2[2-7])/.test(r)) return "Mastercard";
  if (/^(34|37)/.test(r)) return "American Express";
  if (/^9792/.test(r)) return "Troy";
  return null;
}
