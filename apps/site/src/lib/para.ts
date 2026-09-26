/**
 * Kuruşu görüntülenecek metne çevirir.
 *
 * Tutarlar her yerde tam sayı kuruş olarak tutulur; kayan noktalı para
 * toplandıkça sapar. Bu yüzden fonksiyon girdinin tam sayı olmasını zorlar:
 * ondalıklı bir değer buraya kadar geldiyse yukarıda bir yerde bozulmuş
 * demektir ve sessizce yuvarlamak o hatayı gizlerdi.
 */
export function kurusBicimle(kurus: number, paraBirimi = "TRY"): string {
  if (!Number.isInteger(kurus)) {
    throw new TypeError(`Tutar tam sayı kuruş olmalı, alınan: ${kurus}`);
  }

  return new Intl.NumberFormat("tr-TR", {
    style: "currency",
    currency: paraBirimi,
  }).format(kurus / 100);
}

/**
 * Ondalıklı sayıyı Türkçe yazımla verir: ayraç virgül.
 *
 * Şablon dizgisine doğrudan konan bir sayı "2.5882" üretiyordu; Türkçe metnin
 * içinde nokta ondalık değil binlik ayracı gibi okunuyor. Tek tek
 * `replace(".", ",")` yazmak da bir süre sonra bir yerde unutuluyor.
 */
export function sayiBicimle(deger: number, basamak = 2): string {
  return new Intl.NumberFormat("tr-TR", {
    minimumFractionDigits: basamak,
    maximumFractionDigits: basamak,
  }).format(deger);
}
