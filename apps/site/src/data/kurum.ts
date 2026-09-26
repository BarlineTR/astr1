/**
 * Kurum bilgileri — **YER TUTUCU** (bkz. `docs/RISKLER.md` R3).
 *
 * Gerçek ticari unvan, vergi numarası, adres ve ETBİS kaydı henüz verilmedi.
 * Hukuki sayfalar ve iyzico başvurusu bu değerlerle tamamlanamaz; ödeme fazı bu
 * dosya gerçek bilgiyle dolmadan yayına çıkmaz.
 *
 * Gerçek bilgi geldiğinde değiştirilecek tek yer burasıdır. `YER_TUTUCU`
 * bayrağı doğru olduğu sürece site alt bilgisinde ve hukuki sayfalarda görünür
 * bir uyarı çizilir — yer tutucu bilgiyle yayına çıkmak fark edilmeden mümkün
 * olmasın.
 */
export const KURUM = {
  YER_TUTUCU: true,

  kisaAd: "ASTRO",
  unvan: "[YER TUTUCU] Barline Robotik",
  vergiNo: "[YER TUTUCU]",
  vergiDairesi: "[YER TUTUCU]",
  adres: "[YER TUTUCU] Türkiye",
  telefon: "[YER TUTUCU]",
  eposta: "iletisim@example.invalid",
  etbis: "[YER TUTUCU]",

  /** Canonical ve OG adresleri buradan türetilir. */
  siteUrl: process.env.NEXT_PUBLIC_SITE_URL ?? "http://localhost:3000",
  repoUrl: "https://github.com/BarlineTR/astr1",
} as const;
