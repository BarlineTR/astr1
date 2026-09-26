"use client";

import { useSearchParams } from "next/navigation";
import { useActionState } from "react";

import { girisYap, type GirisSonuc } from "@/app/giris/actions";

const BASLANGIC: GirisSonuc | null = null;

/**
 * Giriş formu.
 *
 * Sunucu eylemiyle gönderilir: JavaScript kapalıyken de çalışır. Girişten
 * sonra dönülecek sayfa gizli alanda taşınır ve sunucuda `guvenliDonusYolu`
 * ile süzülür — dış adres kabul edilmez.
 */
export function GirisFormu() {
  const [durum, gonder, bekliyor] = useActionState(girisYap, BASLANGIC);
  const devam = useSearchParams().get("devam");

  return (
    <form className="form" action={gonder} noValidate>
      {durum?.hata && (
        <p className="form__hata" role="alert">
          {durum.hata}
        </p>
      )}

      <input type="hidden" name="devam" value={devam ?? ""} />

      <div className="form__alan">
        <label htmlFor="eposta">E-posta</label>
        <input id="eposta" type="email" name="eposta" autoComplete="email" required />
      </div>

      <div className="form__alan">
        <label htmlFor="parola">Parola</label>
        <input
          id="parola"
          type="password"
          name="parola"
          autoComplete="current-password"
          required
        />
      </div>

      <button className="btn btn--primary" type="submit" disabled={bekliyor}>
        {bekliyor ? "Giriş yapılıyor…" : "Giriş yap"}
      </button>
    </form>
  );
}
