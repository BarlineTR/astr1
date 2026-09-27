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
  const [musteriEposta, setMusteriEposta] = useState("");
  const [musteriTelefon, setMusteriTelefon] = useState("");
  const [musteriSifre, setMusteriSifre] = useState("");
  const [sonKullanma, setSonKullanma] = useState("");
  const [cvc, setCvc] = useState("");
  const [otp, setOtp] = useState("");
  const [faturaTipi, setFaturaTipi] = useState<"bireysel" | "kurumsal" | "">("");
  const [firmaAdi, setFirmaAdi] = useState("");
  const [vergiNo, setVergiNo] = useState("");
  const [tipKurus, setTipKurus] = useState<number>(0);
  const [hatalar, setHatalar] = useState<Record<string, string>>({});
  const [genelHata, setGenelHata] = useState<string | null>(null);

  const aile = kartAilesi(numara);
  const toplamTutarKurus = tutarKurus + tipKurus;

  function kartiDogrula(): boolean {
    const yeni: Record<string, string> = {};

    if (adSoyad.trim().length < 3) yeni.adSoyad = "Lütfen adınızı ve soyadınızı yazın.";
    if (!musteriEposta.includes("@") || musteriEposta.trim().length < 5) {
      yeni.musteriEposta = "Geçerli bir e-posta adresi yazın.";
    }
    if (musteriTelefon.replace(/\D/g, "").length < 10) {
      yeni.musteriTelefon = "Geçerli bir telefon numarası girin (Örn: 05XX...).";
    }
    if (musteriSifre && musteriSifre.length < 8) {
      yeni.musteriSifre = "Şifre en az 8 karakter olmalı.";
    }

    if (!faturaTipi) {
      yeni.faturaTipi = "Lütfen müşteri / fatura tipini seçin (Zorunlu alan).";
    } else if (faturaTipi === "kurumsal") {
      if (firmaAdi.trim().length < 2) yeni.firmaAdi = "Firma unvanını girin.";
      if (vergiNo.trim().length < 10) yeni.vergiNo = "Geçerli bir Vergi Kimlik Numarası (VKN/TCKN) girin.";
    }

    if (!luhnGecerliMi(numara)) yeni.numara = "Kart numarası geçersiz.";
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
        <p className="odeme-ekrani__tutar mono">{kurusBicimle(toplamTutarKurus)}</p>
        <p className="odeme-ekrani__kalem">
          {kalemAdi}
          {periyot === "ay" && <span className="odeme-ekrani__periyot"> · aylık yenilenir</span>}
          {tipKurus > 0 && <span> (+{kurusBicimle(tipKurus)} bahşiş/katkı)</span>}
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
          {/* Müşteri ve İletişim Bilgileri */}
          <div className="form__alan">
            <label htmlFor="ad-soyad">Ad Soyad *</label>
            <input
              id="ad-soyad"
              value={adSoyad}
              placeholder="Adınız ve Soyadınız"
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
              <label htmlFor="musteri-eposta">E-posta Adresi *</label>
              <input
                id="musteri-eposta"
                type="email"
                value={musteriEposta}
                placeholder="ornek@firma.com"
                onChange={(e) => setMusteriEposta(e.target.value)}
              />
              {hatalar.musteriEposta && (
                <small className="form__alan-hata" role="alert">
                  {hatalar.musteriEposta}
                </small>
              )}
            </div>

            <div className="form__alan">
              <label htmlFor="musteri-telefon">Telefon Numarası *</label>
              <input
                id="musteri-telefon"
                type="tel"
                value={musteriTelefon}
                placeholder="05XX XXX XX XX"
                onChange={(e) => setMusteriTelefon(e.target.value)}
              />
              {hatalar.musteriTelefon && (
                <small className="form__alan-hata" role="alert">
                  {hatalar.musteriTelefon}
                </small>
              )}
            </div>
          </div>

          <div className="form__alan">
            <label htmlFor="musteri-sifre">Hesap Parolası (Opsiyonel / Yeni Hesap Açılışı İçin)</label>
            <input
              id="musteri-sifre"
              type="password"
              value={musteriSifre}
              placeholder="En az 8 karakterli parola"
              onChange={(e) => setMusteriSifre(e.target.value)}
            />
            {hatalar.musteriSifre && (
              <small className="form__alan-hata" role="alert">
                {hatalar.musteriSifre}
              </small>
            )}
          </div>

          {/* Zorunlu Müşteri / Fatura Tipi */}
          <div className="form__alan">
            <label>
              Müşteri & Fatura Tipi <span style={{ color: "var(--color-alarm, #ef4444)" }}>* (Zorunlu)</span>
            </label>
            <div style={{ display: "flex", gap: "1rem", marginTop: "0.25rem" }}>
              <label style={{ display: "inline-flex", alignItems: "center", gap: "0.4rem", cursor: "pointer" }}>
                <input
                  type="radio"
                  name="faturaTipi"
                  value="bireysel"
                  checked={faturaTipi === "bireysel"}
                  onChange={() => setFaturaTipi("bireysel")}
                />
                Bireysel
              </label>
              <label style={{ display: "inline-flex", alignItems: "center", gap: "0.4rem", cursor: "pointer" }}>
                <input
                  type="radio"
                  name="faturaTipi"
                  value="kurumsal"
                  checked={faturaTipi === "kurumsal"}
                  onChange={() => setFaturaTipi("kurumsal")}
                />
                Kurumsal (Şirket)
              </label>
            </div>
            {hatalar.faturaTipi && (
              <small className="form__alan-hata" role="alert">
                {hatalar.faturaTipi}
              </small>
            )}
          </div>

          {faturaTipi === "kurumsal" && (
            <div className="odeme-ekrani__ikili">
              <div className="form__alan">
                <label htmlFor="firma-ad">Firma Unvanı</label>
                <input
                  id="firma-ad"
                  value={firmaAdi}
                  placeholder="Şirket Tam Adı A.Ş."
                  onChange={(e) => setFirmaAdi(e.target.value)}
                />
                {hatalar.firmaAdi && (
                  <small className="form__alan-hata" role="alert">
                    {hatalar.firmaAdi}
                  </small>
                )}
              </div>
              <div className="form__alan">
                <label htmlFor="vergi-no">Vergi Kimlik No (VKN)</label>
                <input
                  id="vergi-no"
                  value={vergiNo}
                  inputMode="numeric"
                  placeholder="10 Haneli VKN"
                  onChange={(e) => setVergiNo(e.target.value.replace(/\D/g, "").slice(0, 11))}
                />
                {hatalar.vergiNo && (
                  <small className="form__alan-hata" role="alert">
                    {hatalar.vergiNo}
                  </small>
                )}
              </div>
            </div>
          )}

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

          {/* Proje Bahşişi / Destek Katkısı (Tip) */}
          <div className="form__alan" style={{ borderTop: "1px dashed var(--color-border, #333)", paddingTop: "0.75rem" }}>
            <label>Geliştiriciye Destek / Bahşiş (Tip)</label>
            <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap", marginTop: "0.25rem" }}>
              {[
                { etiket: "Katkısız", kurus: 0 },
                { etiket: "+50 ₺ Çay", kurus: 5000 },
                { etiket: "+150 ₺ Kahve", kurus: 15000 },
                { etiket: "+500 ₺ Devre", kurus: 50000 },
              ].map((secenek) => (
                <button
                  type="button"
                  key={secenek.kurus}
                  className={`btn btn--small ${tipKurus === secenek.kurus ? "btn--primary" : "btn--quiet"}`}
                  onClick={() => setTipKurus(secenek.kurus)}
                >
                  {secenek.etiket}
                </button>
              ))}
            </div>
          </div>

          <button className="btn btn--primary" type="submit">
            {kurusBicimle(toplamTutarKurus)}
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
