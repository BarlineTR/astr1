"use client";

import { useActionState } from "react";

import { satinAl, type SatinAlSonuc } from "@/app/panel/abonelik/actions";

const BASLANGIC: SatinAlSonuc | null = null;

/**
 * Satın alma düğmesi.
 *
 * Forma yalnızca ürün slug'ı konuyor; tutar sunucudaki listeden okunuyor.
 * Fiyatı istemcinin göndermesi, tutarı değiştirip bir kuruşa satın almaya izin
 * verirdi.
 */
export function SatinAlDugmesi({
  slug,
  etiket,
  kapali = false,
}: {
  slug: string;
  etiket: string;
  /** Zaten abonelik varsa ikinci plan seçilemez: iki kez tahsilat demek. */
  kapali?: boolean;
}) {
  const [durum, gonder, bekliyor] = useActionState(satinAl, BASLANGIC);

  return (
    <form action={gonder}>
      <input type="hidden" name="slug" value={slug} />
      <button className="btn" type="submit" disabled={bekliyor || kapali}>
        {bekliyor ? "Yönlendiriliyor…" : etiket}
      </button>
      {durum?.hata && (
        <p className="form__alan-hata" role="alert">
          {durum.hata}
        </p>
      )}
    </form>
  );
}
