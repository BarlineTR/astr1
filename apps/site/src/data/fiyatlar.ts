/**
 * Fiyatlar — **GELİŞTİRME DEĞERLERİ** (`docs/RISKLER.md` R4).
 *
 * Gerçek fiyat listesi henüz verilmedi. Buradaki tutarlar ödeme akışını uçtan
 * uca çalıştırabilmek için uydurulmuştur; ödeme fazı bu bayrak kalkmadan yayına
 * alınmaz ve fiyatlandırma sayfası bayrak açıkken görünür bir uyarı çizer.
 *
 * Tutarlar tam sayı kuruştur: 199,90 TL → 19990. Para hiçbir yerde kayan
 * noktayla tutulmaz.
 */
export const GELISTIRME_FIYATI = true;

export interface Kalem {
  readonly slug: string;
  readonly ad: string;
  readonly aciklama: string;
  readonly fiyatKurus: number;
  readonly periyot: "tek" | "ay";
  readonly ozellikler?: readonly string[];
}

/**
 * Destek paketleri.
 *
 * "Bağış" değil, dijital ürün satışı: Türkiye'de yardım toplamak 2860 sayılı
 * kanuna tabi ve izin gerektiriyor. Aynı para akışı ürün satışı olarak
 * kurgulandığında olağan bir satıştır.
 */
export const DESTEK_PAKETLERI: readonly Kalem[] = [
  {
    slug: "cay",
    ad: "Çay",
    aciklama: "Küçük bir teşekkür. Adınız destekçiler listesinde görünür.",
    fiyatKurus: 5000,
    periyot: "tek",
  },
  {
    slug: "kahve",
    ad: "Kahve",
    aciklama: "Bir sonraki prototipin lehimine katkı.",
    fiyatKurus: 15000,
    periyot: "tek",
  },
  {
    slug: "devre",
    ad: "Devre",
    aciklama: "Bir sensör kartı kadar destek.",
    fiyatKurus: 50000,
    periyot: "tek",
  },
];

export const PLANLAR: readonly Kalem[] = [
  {
    slug: "gozlem",
    ad: "Gözlem",
    aciklama: "Tek robot, telemetri izleme.",
    fiyatKurus: 49900,
    periyot: "ay",
    ozellikler: ["1 robot", "Canlı telemetri", "30 gün kayıt geçmişi", "E-posta desteği"],
  },
  {
    slug: "operasyon",
    ad: "Operasyon",
    aciklama: "Uzaktan kontrol ve teşhis.",
    fiyatKurus: 149900,
    periyot: "ay",
    ozellikler: [
      "5 robota kadar",
      "Uzaktan kafa kontrolü",
      "Log ve teşhis erişimi",
      "Rol bazlı operatör yetkisi",
      "Öncelikli destek",
    ],
  },
];
