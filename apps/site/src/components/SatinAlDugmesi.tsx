"use client";

import { useActionState, useState } from "react";
import Link from "next/link";

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
  oturumVar = true,
  periyot = "tek",
  sinif = "btn btn--primary",
}: {
  slug: string;
  etiket: string;
  /** Zaten abonelik varsa ikinci plan seçilemez: iki kez tahsilat demek. */
  kapali?: boolean;
  oturumVar?: boolean;
  periyot?: "tek" | "ay";
  sinif?: string;
}) {
  const [durum, gonder, bekliyor] = useActionState(satinAl, BASLANGIC);
  const [misafirAcik, setMisafirAcik] = useState(false);

  // Oturum yok ve aylık plan ise -> Giriş yapmaya yönlendir
  if (!oturumVar && periyot === "ay") {
    return (
      <Link
        href="/giris?donus=/fiyatlandirma"
        className={sinif}
        style={{ width: "100%", textAlign: "center", display: "inline-block" }}
      >
        Giriş Yap ve {etiket}
      </Link>
    );
  }

  // Oturum yok ve tek seferlik destek paketi ise -> Tıklayınca hızlıca e-posta & ad sor
  if (!oturumVar && !misafirAcik) {
    return (
      <button
        className={sinif}
        type="button"
        onClick={() => setMisafirAcik(true)}
        style={{ width: "100%" }}
      >
        {etiket}
      </button>
    );
  }

  return (
    <form action={gonder} style={{ width: "100%" }}>
      <input type="hidden" name="slug" value={slug} />

      {!oturumVar && misafirAcik && (
        <div style={{ marginBottom: "0.75rem", display: "flex", flexDirection: "column", gap: "0.5rem" }}>
          <div>
            <label style={{ display: "block", fontSize: "0.8rem", color: "var(--ink-muted, #a1a1aa)", marginBottom: "0.2rem" }}>
              Ad Soyad
            </label>
            <input
              type="text"
              name="ad"
              required
              placeholder="Örn: Ahmet Yılmaz"
              className="form__alan"
              style={{ width: "100%", padding: "0.4rem 0.6rem", fontSize: "0.85rem" }}
            />
          </div>
          <div>
            <label style={{ display: "block", fontSize: "0.8rem", color: "var(--ink-muted, #a1a1aa)", marginBottom: "0.2rem" }}>
              E-posta (Dekont ve teşekkür için)
            </label>
            <input
              type="email"
              name="eposta"
              required
              placeholder="ahmet@example.com"
              className="form__alan"
              style={{ width: "100%", padding: "0.4rem 0.6rem", fontSize: "0.85rem" }}
            />
          </div>
        </div>
      )}

      <button
        className={sinif}
        type="submit"
        disabled={bekliyor || kapali}
        style={{ width: "100%" }}
      >
        {bekliyor ? "Ödeme Başlatılıyor…" : etiket}
      </button>

      {durum?.hata && (
        <p className="form__alan-hata" role="alert" style={{ marginTop: "0.5rem", fontSize: "0.85rem" }}>
          {durum.hata}
        </p>
      )}
    </form>
  );
}
