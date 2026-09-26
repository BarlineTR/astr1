import { IBM_Plex_Mono, Inter, Source_Serif_4 } from "next/font/google";

/**
 * Yazı tipleri.
 *
 * `next/font` dosyaları kendi kökümüzden servis eder; önceki `<link
 * rel="stylesheet">` Google'a fazladan bir gidiş-dönüş ve yazı tipi geldiğinde
 * bir düzen kayması demekti.
 *
 * `latin-ext` alt kümesi zorunlu: ğ, ş, ı, İ, ö, ü, ç harfleri `latin` içinde
 * yok ve onsuz Türkçe metin yedek yazı tipine düşüyor.
 *
 * Değişken adları `tokens.css` içindeki --font-*-loaded belirteçleriyle eşleşir.
 */
export const serif = Source_Serif_4({
  subsets: ["latin", "latin-ext"],
  variable: "--font-display-loaded",
  display: "swap",
});

export const ui = Inter({
  subsets: ["latin", "latin-ext"],
  variable: "--font-ui-loaded",
  display: "swap",
});

export const mono = IBM_Plex_Mono({
  subsets: ["latin", "latin-ext"],
  weight: ["400", "500"],
  variable: "--font-mono-loaded",
  display: "swap",
});
