/**
 * Yönetim ekibi — **YER TUTUCU** (`docs/RISKLER.md` R3).
 *
 * Liste bilerek boş. Uydurma isim yazmak yerine sayfa "yakında" diyor; böylece
 * eksik bilgi görünür kalıyor ve yanlış bir isim yayına çıkmıyor.
 */
export const YONETIM: ReadonlyArray<{
  readonly ad: string;
  readonly unvan: string;
  readonly tanitim: string;
}> = [];

export const BASIN = {
  lead:
    "Basın mensupları ve iş ortaklarımız için marka varlıkları ve kurumsal " +
    "künye bilgileri.",
  /**
   * Varlık dosyaları henüz hazırlanmadı (R3 ile aynı paket). Liste boşken sayfa
   * bunu söyler; var olmayan dosyaya bağlantı vermez.
   */
  varliklar: [] as ReadonlyArray<{ ad: string; href: string; not: string }>,
} as const;
