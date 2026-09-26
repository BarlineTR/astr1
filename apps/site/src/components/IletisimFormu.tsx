"use client";

import Link from "next/link";
import { useActionState } from "react";

import { iletisimGonder, type GonderSonuc } from "@/app/iletisim/actions";

const BASLANGIC: GonderSonuc | null = null;

export function IletisimFormu({ tur }: { tur: "iletisim" | "teklif" }) {
  const [durum, gonder, bekliyor] = useActionState(iletisimGonder, BASLANGIC);

  if (durum?.ok) {
    return (
      <p className="form__basari" role="status">
        Talebiniz alındı. En kısa sürede dönüş yapacağız.
      </p>
    );
  }

  const hata = (alan: string) => durum?.hatalar?.[alan];

  return (
    /*
     * Sunucu eylemi: JavaScript kapalıyken de gönderilebiliyor. Sayfanın metni
     * betik olmadan okunabiliyorsa form da çalışmalı.
     */
    <form className="form" action={gonder} noValidate>
      <input type="hidden" name="tur" value={tur} />
      <input type="hidden" name="kaynakSayfa" value={tur === "teklif" ? "/iletisim#teklif" : "/iletisim"} />

      {durum?.genelHata && (
        <p className="form__hata" role="alert">
          {durum.genelHata}
        </p>
      )}

      <div className="form__alan">
        <label htmlFor={`${tur}-ad`}>Ad soyad</label>
        <input id={`${tur}-ad`} type="text" name="ad" autoComplete="name" required />
        {hata("ad") && (
          <small className="form__alan-hata" role="alert">
            {hata("ad")}
          </small>
        )}
      </div>

      <div className="form__alan">
        <label htmlFor={`${tur}-eposta`}>E-posta</label>
        <input id={`${tur}-eposta`} type="email" name="eposta" autoComplete="email" required />
        {hata("eposta") && (
          <small className="form__alan-hata" role="alert">
            {hata("eposta")}
          </small>
        )}
      </div>

      <div className="form__alan">
        <label htmlFor={`${tur}-sirket`}>
          Kurum {tur === "teklif" ? "" : <span className="form__istege-bagli">(isteğe bağlı)</span>}
        </label>
        <input
          id={`${tur}-sirket`}
          type="text"
          name="sirket"
          autoComplete="organization"
          required={tur === "teklif"}
        />
        {hata("sirket") && (
          <small className="form__alan-hata" role="alert">
            {hata("sirket")}
          </small>
        )}
      </div>

      <div className="form__alan">
        <label htmlFor={`${tur}-telefon`}>
          Telefon <span className="form__istege-bagli">(isteğe bağlı)</span>
        </label>
        <input id={`${tur}-telefon`} type="tel" name="telefon" autoComplete="tel" />
      </div>

      <div className="form__alan">
        <label htmlFor={`${tur}-mesaj`}>Mesajınız</label>
        <textarea id={`${tur}-mesaj`} name="mesaj" required minLength={20} />
        {hata("mesaj") && (
          <small className="form__alan-hata" role="alert">
            {hata("mesaj")}
          </small>
        )}
      </div>

      {/*
        Tuzak alan: gerçek kullanıcı görmez ve doldurmaz, dolu geldiyse gönderen
        bir bot. CAPTCHA'sız ve JavaScript gerektirmeyen ucuz bir filtre.
        aria-hidden + tabIndex: ekran okuyucu da atlar.
      */}
      <div className="tuzak" aria-hidden="true">
        <label htmlFor={`${tur}-website`}>Web sitesi</label>
        <input id={`${tur}-website`} type="text" name="website" tabIndex={-1} autoComplete="off" />
      </div>

      <label className="form__onay">
        <input type="checkbox" name="kvkkOnay" />
        <span>
          <Link href="/kvkk">KVKK aydınlatma metnini</Link> okudum, verilerimin bu talep
          kapsamında işlenmesini kabul ediyorum.
        </span>
      </label>
      {hata("kvkkOnay") && (
        <p className="form__hata" role="alert">
          {hata("kvkkOnay")}
        </p>
      )}

      <button className="btn btn--primary" type="submit" disabled={bekliyor}>
        {bekliyor ? "Gönderiliyor…" : tur === "teklif" ? "Teklif isteyin" : "Gönderin"}
      </button>
    </form>
  );
}
