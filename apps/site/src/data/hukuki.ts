/**
 * Hukuki metinler — **YER TUTUCU** (`docs/RISKLER.md` R2).
 *
 * Hiçbiri hukukçu onayından geçmedi ve sayfalar bunu kendi üstlerinde söylüyor.
 * Ödeme fazı bu metinler onaylanmadan yayına çıkmaz.
 *
 * Sürüm numarası önemli: onay kayıtları buna referans veriyor ve metin
 * değiştiğinde sürüm artmalı, yoksa eski onayların hangi metne verildiği
 * kaybolur.
 */
export const KVKK_METIN_SURUMU = "2026-09-26-taslak";

export interface HukukiMetin {
  readonly slug: string;
  readonly baslik: string;
  readonly surum: string;
  readonly govde: readonly string[];
}

const TASLAK_UYARISI = true;
export const HUKUKI_YER_TUTUCU = TASLAK_UYARISI;
