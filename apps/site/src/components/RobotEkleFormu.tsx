"use client";

import Link from "next/link";
import { useActionState } from "react";

import { robotEkle, type RobotEkleSonuc } from "@/app/panel/cihaz/ekle/actions";

const BASLANGIC: RobotEkleSonuc | null = null;

export function RobotEkleFormu() {
  const [durum, gonder, bekliyor] = useActionState(robotEkle, BASLANGIC);

  if (durum?.ok && durum.kod) {
    return (
      <div className="eslestirme">
        <p className="form__basari" role="status">
          <strong>{durum.cihazAdi}</strong> eklendi.
        </p>

        <div className="eslestirme__kutu">
          <p className="eyebrow">Eşleştirme kodu</p>
          <p className="eslestirme__kod mono">{durum.kod}</p>
          <p className="eslestirme__not">
            Bu kod <strong>yalnızca bir kez</strong> gösteriliyor; veritabanında
            yalnızca özeti duruyor. Kaybederseniz cihaz sayfasından yenisini
            üretebilirsiniz. Kod 24 saat geçerli.
          </p>
        </div>

        <p className="eslestirme__sonraki">
          Robot tarafındaki ajan bu kodu kullanarak bağlanacak. Uzaktan erişim ağ
          geçidi hazırlanıyor; o zamana kadar cihaz <em>eşleştirme bekliyor</em>
          durumunda kalır.
        </p>

        <Link className="btn" href="/panel">
          Cihazlara dön
        </Link>
      </div>
    );
  }

  const hata = (alan: string) => durum?.hatalar?.[alan];

  return (
    <form className="form" action={gonder} noValidate>
      {hata("genel") && (
        <p className="form__hata" role="alert">
          {hata("genel")}
        </p>
      )}

      <div className="form__alan">
        <label htmlFor="ad">Robot adı</label>
        <input id="ad" type="text" name="ad" required maxLength={80} />
        {hata("ad") && (
          <small className="form__alan-hata" role="alert">
            {hata("ad")}
          </small>
        )}
      </div>

      <div className="form__alan">
        <label htmlFor="seri">Seri numarası</label>
        <input
          id="seri"
          type="text"
          name="seri"
          required
          maxLength={64}
          aria-describedby="seri-ipucu"
          placeholder="ASTRO-V1-000123"
        />
        <small className="form__ipucu" id="seri-ipucu">
          Robotun gövdesindeki etikette yazar.
        </small>
        {hata("seri") && (
          <small className="form__alan-hata" role="alert">
            {hata("seri")}
          </small>
        )}
      </div>

      <button className="btn btn--primary" type="submit" disabled={bekliyor}>
        {bekliyor ? "Ekleniyor…" : "Robotu ekle"}
      </button>
    </form>
  );
}
