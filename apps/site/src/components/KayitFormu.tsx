"use client";

import Link from "next/link";
import { useActionState } from "react";

import { kayitOl, type KayitSonuc } from "@/app/kayit/actions";

const BASLANGIC: KayitSonuc | null = null;

/**
 * Kayıt formu.
 *
 * Sunucu eylemiyle gönderilir: JavaScript kapalıyken de çalışır, onay kutusu
 * sunucuda zorunludur ve hesap ile KVKK onayı aynı akışta yazılır.
 */
export function KayitFormu() {
  const [durum, gonder, bekliyor] = useActionState(kayitOl, BASLANGIC);
  const hata = (alan: string) => durum?.hatalar?.[alan];

  return (
    <form className="form" action={gonder} noValidate>
      {hata("genel") && (
        <p className="form__hata" role="alert">
          {hata("genel")}
        </p>
      )}

      <div className="form__alan">
        <label htmlFor="ad">Ad soyad</label>
        <input id="ad" type="text" name="ad" autoComplete="name" required />
        {hata("ad") && (
          <small className="form__alan-hata" role="alert">
            {hata("ad")}
          </small>
        )}
      </div>

      <div className="form__alan">
        <label htmlFor="eposta">E-posta</label>
        <input id="eposta" type="email" name="eposta" autoComplete="email" required />
        {hata("eposta") && (
          <small className="form__alan-hata" role="alert">
            {hata("eposta")}
          </small>
        )}
      </div>

      {/*
        İpucu etiketin içinde değil: label'ın içindeki her metin erişilebilir
        ada katılıyor ve alan "Parola En az 10 karakter." diye okunuyordu.
      */}
      <div className="form__alan">
        <label htmlFor="parola">Parola</label>
        <input
          id="parola"
          type="password"
          name="parola"
          autoComplete="new-password"
          aria-describedby="parola-ipucu"
          required
          minLength={10}
        />
        <small className="form__ipucu" id="parola-ipucu">
          En az 10 karakter.
        </small>
        {hata("parola") && (
          <small className="form__alan-hata" role="alert">
            {hata("parola")}
          </small>
        )}
      </div>

      <label className="form__onay">
        <input type="checkbox" name="kvkkOnay" />
        <span>
          <Link href="/kvkk">KVKK aydınlatma metnini</Link> okudum, kişisel verilerimin
          işlenmesini kabul ediyorum.
        </span>
      </label>
      {hata("kvkkOnay") && (
        <p className="form__hata" role="alert">
          {hata("kvkkOnay")}
        </p>
      )}

      <button className="btn btn--primary" type="submit" disabled={bekliyor}>
        {bekliyor ? "Hesap oluşturuluyor…" : "Hesap oluştur"}
      </button>
    </form>
  );
}
