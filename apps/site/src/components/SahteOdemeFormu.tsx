"use client";

import { useState } from "react";

import {
  cvcGecerliMi,
  kartAilesi,
  kartNumarasiBicimle,
  luhnGecerliMi,
  sonKullanmaGecerliMi,
} from "@/lib/odeme/kart";
import { kurusBicimle } from "@/lib/para";

/**
 * Taklit ödeme ekranı.
 *
 * Gerçek akışta bu adım iyzico'nun kendi sayfasında geçer ve kart bilgisi bizim
 * sunucumuza hiç uğramaz. Bu ekran yalnızca iyzico anahtarları tanımlı değilken
 * görünür ve iki işi var: akışın tamamını anahtar olmadan koşturabilmek, ve
 * ödeme adımının kullanıcıya nasıl görüneceğini göstermek.
 *
 * Bilerek **iyzico markası kullanılmıyor**: başka bir şirketin ödeme sayfasının
 * taklidini üretmek, gerçeğiyle karıştırılabilecek bir şey yapmak olurdu.
 * Ekranın kendisi de taklit olduğunu üstünde yazıyor.
 *
 * Girilen kart numarası hiçbir yere gönderilmiyor — doğrulama tarayıcıda
 * yapılıyor ve sunucuya yalnızca "onaylandı / reddedildi" bilgisi gidiyor.
 */

type Adim = "kart" | "dogrulama" | "gonderiliyor";

/** Sandbox'ta OTP sabittir; taklit ekran da aynı davranıyor. */
const TAKLIT_OTP = "123456";

export function SahteOdemeFormu({
  token,
  tutarKurus,
  kalemAdi,
  periyot,
  kararUcu = "/api/odeme/sahte-karar",
  geriDonusUcu = "/api/odeme/geri-donus",
}: {
  token: string;
  tutarKurus: number;
  kalemAdi: string;
  periyot: "tek" | "ay";
  /** Abonelik ve tek seferlik ödeme ayrı uçlar kullanıyor. */
  kararUcu?: string;
  geriDonusUcu?: string;
}) {
  const [adim, setAdim] = useState<Adim>("kart");
  const [numara, setNumara] = useState("");
  const [adSoyad, setAdSoyad] = useState("");
  const [sonKullanma, setSonKullanma] = useState("");
  const [cvc, setCvc] = useState("");
  const [otp, setOtp] = useState("");
  const [hatalar, setHatalar] = useState<Record<string, string>>({});
  const [genelHata, setGenelHata] = useState<string | null>(null);

  const aile = kartAilesi(numara);

  function kartiDogrula(): boolean {
    const yeni: Record<string, string> = {};
    if (!luhnGecerliMi(numara)) yeni.numara = "Kart numarası geçersiz.";
    if (adSoyad.trim().length < 3) yeni.adSoyad = "Kart üzerindeki adı yazın.";
    if (!sonKullanmaGecerliMi(sonKullanma)) yeni.sonKullanma = "AA/YY biçiminde ve gelecekte olmalı.";
    if (!cvcGecerliMi(cvc)) yeni.cvc = "CVC 3 ya da 4 hane.";
    setHatalar(yeni);
    return Object.keys(yeni).length === 0;
  }

  async function kararGonder(sonuc: "basarili" | "basarisiz") {
    setAdim("gonderiliyor");
    await fetch(kararUcu, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ token, sonuc }),
    });

    /*
     * Gerçek sağlayıcının yaptığının aynısı: geri dönüş adresine token POST'u.
     * Böylece sonraki bütün adımlar (sonuç alma, idempotensi, sipariş durumu)
     * gerçeğiyle aynı yolu izliyor.
     */
    const form = document.createElement("form");
    form.method = "POST";
    form.action = geriDonusUcu;
    const alan = document.createElement("input");
    alan.name = "token";
    alan.value = token;
    form.appendChild(alan);
    document.body.appendChild(form);
    form.submit();
  }

  return (
    <div className="odeme-ekrani">
      <div className="odeme-ekrani__ozet">
        <p className="eyebrow">Ödenecek tutar</p>
        <p className="odeme-ekrani__tutar mono">{kurusBicimle(tutarKurus)}</p>
        <p className="odeme-ekrani__kalem">
          {kalemAdi}
          {periyot === "ay" && <span className="odeme-ekrani__periyot"> · aylık yenilenir</span>}
        </p>
      </div>

      {adim === "kart" && (
        <form
          className="form odeme-ekrani__form"
          onSubmit={(e) => {
            e.preventDefault();
            setGenelHata(null);
            if (kartiDogrula()) setAdim("dogrulama");
          }}
          noValidate
        >
          <div className="form__alan">
            <label htmlFor="kart-numara">Kart numarası</label>
            <div className="odeme-ekrani__kart-alani">
              <input
                id="kart-numara"
                inputMode="numeric"
                autoComplete="off"
                placeholder="0000 0000 0000 0000"
                value={numara}
                onChange={(e) => setNumara(kartNumarasiBicimle(e.target.value))}
              />
              {aile && <span className="odeme-ekrani__aile">{aile}</span>}
            </div>
            {hatalar.numara && (
              <small className="form__alan-hata" role="alert">
                {hatalar.numara}
              </small>
            )}
          </div>

          <div className="form__alan">
            <label htmlFor="kart-ad">Kart üzerindeki ad</label>
            <input
              id="kart-ad"
              autoComplete="off"
              value={adSoyad}
              onChange={(e) => setAdSoyad(e.target.value)}
            />
            {hatalar.adSoyad && (
              <small className="form__alan-hata" role="alert">
                {hatalar.adSoyad}
              </small>
            )}
          </div>

          <div className="odeme-ekrani__ikili">
            <div className="form__alan">
              <label htmlFor="kart-tarih">Son kullanma</label>
              <input
                id="kart-tarih"
                inputMode="numeric"
                placeholder="AA/YY"
                autoComplete="off"
                value={sonKullanma}
                onChange={(e) => {
                  const r = e.target.value.replace(/\D/g, "").slice(0, 4);
                  setSonKullanma(r.length > 2 ? `${r.slice(0, 2)}/${r.slice(2)}` : r);
                }}
              />
              {hatalar.sonKullanma && (
                <small className="form__alan-hata" role="alert">
                  {hatalar.sonKullanma}
                </small>
              )}
            </div>

            <div className="form__alan">
              <label htmlFor="kart-cvc">CVC</label>
              <input
                id="kart-cvc"
                inputMode="numeric"
                placeholder="000"
                autoComplete="off"
                value={cvc}
                onChange={(e) => setCvc(e.target.value.replace(/\D/g, "").slice(0, 4))}
              />
              {hatalar.cvc && (
                <small className="form__alan-hata" role="alert">
                  {hatalar.cvc}
                </small>
              )}
            </div>
          </div>

          <button className="btn btn--primary" type="submit">
            {kurusBicimle(tutarKurus)}
            {periyot === "ay" ? " / ay abone ol" : " öde"}
          </button>

          <button
            className="btn btn--quiet odeme-ekrani__vazgec"
            type="button"
            onClick={() => kararGonder("basarisiz")}
          >
            Vazgeç
          </button>
        </form>
      )}

      {adim === "dogrulama" && (
        <form
          className="form odeme-ekrani__form"
          onSubmit={(e) => {
            e.preventDefault();
            if (otp.trim() !== TAKLIT_OTP) {
              setGenelHata("Doğrulama kodu hatalı.");
              return;
            }
            void kararGonder("basarili");
          }}
          noValidate
        >
          <p className="odeme-ekrani__3d">
            <strong>3D Secure doğrulaması</strong>
            <br />
            Bankanız {numara.slice(-4)} ile biten kartınız için bir doğrulama kodu
            gönderdi. Gerçek akışta bu adım bankanın sayfasında geçer.
          </p>

          {genelHata && (
            <p className="form__hata" role="alert">
              {genelHata}
            </p>
          )}

          <div className="form__alan">
            <label htmlFor="otp">Doğrulama kodu</label>
            <input
              id="otp"
              inputMode="numeric"
              autoComplete="one-time-code"
              value={otp}
              onChange={(e) => setOtp(e.target.value.replace(/\D/g, "").slice(0, 6))}
            />
            <small className="form__ipucu">
              Taklit ekranda kod sabit: <code className="mono">{TAKLIT_OTP}</code>
            </small>
          </div>

          <button className="btn btn--primary" type="submit">
            Onayla
          </button>

          <button
            className="btn btn--alarm odeme-ekrani__vazgec"
            type="button"
            onClick={() => kararGonder("basarisiz")}
          >
            Ödemeyi reddet
          </button>
        </form>
      )}

      {adim === "gonderiliyor" && (
        <p className="odeme-ekrani__bekleme">Sonuç iletiliyor…</p>
      )}
    </div>
  );
}
