import Link from "next/link";

import { DESTEK_PAKETLERI, GELISTIRME_FIYATI, PLANLAR } from "@/data/fiyatlar";
import { kurusBicimle } from "@/lib/para";
import { oturumGerekli } from "@/lib/oturum";
import { sayfaMetadata } from "@/lib/seo";

export const metadata = sayfaMetadata({
  baslik: "Abonelik",
  aciklama: "Planınız ve ödeme bilgileriniz.",
  yol: "/panel",
  dizinleme: false,
});

export default async function AbonelikSayfasi() {
  await oturumGerekli("/panel/abonelik");

  /*
   * Aktif abonelik henüz tutulmuyor: abonelik kaydı ancak bir ödeme
   * gerçekleştiğinde oluşur ve ödeme sağlayıcısı bağlanmadan ödeme olmuyor.
   * Boş bir `subscriptions` tablosu eklemek, doldurulmayacak bir şema demekti.
   */
  const aktifPlan = null;

  return (
    <>
      <div className="pano__baslik">
        <h1>Abonelik</h1>
        <p className="pano__lead">
          Uzaktan erişim planınız, ödeme yönteminiz ve yenileme bilgileri.
        </p>
      </div>

      <section className="pano__bolum">
        <h2 className="pano__bolum-baslik">Mevcut plan</h2>
        {aktifPlan ? null : (
          <div className="bos-durum">
            <p className="eyebrow">Aktif planınız yok</p>
            <p>
              Panel şu anda ücretsiz kullanılabiliyor. Uzaktan erişim ağ geçidi
              yayına alındığında plan seçmeniz gerekecek.
            </p>
          </div>
        )}
      </section>

      <section className="pano__bolum">
        <h2 className="pano__bolum-baslik">Planlar</h2>
        {GELISTIRME_FIYATI && (
          <p className="uyari-serit">
            Tutarlar geliştirme aşaması değerleridir; gerçek fiyat listesi değildir.
          </p>
        )}

        <div className="fiyat-izgara">
          {PLANLAR.map((plan) => (
            <article className="fiyat-karti" key={plan.slug}>
              <h3 className="fiyat-karti__ad">{plan.ad}</h3>
              <p className="fiyat-karti__tutar mono">
                {kurusBicimle(plan.fiyatKurus)}
                <span className="fiyat-karti__periyot"> / ay</span>
              </p>
              <p className="fiyat-karti__aciklama">{plan.aciklama}</p>
              {plan.ozellikler && (
                <ul className="liste">
                  {plan.ozellikler.map((o) => (
                    <li key={o}>{o}</li>
                  ))}
                </ul>
              )}
              {/*
                Düğme sessizce kırık değil: neden çalışmadığı yazıyor.
                Çalışmayan bir "Satın al" düğmesi, olmayan bir düğmeden kötü.
              */}
              <button className="btn" type="button" disabled>
                Planı seçin
              </button>
              <p className="pano__not">Ödeme altyapısı bağlanınca etkinleşecek.</p>
            </article>
          ))}
        </div>
      </section>

      <section className="pano__bolum">
        <h2 className="pano__bolum-baslik">Ödeme yöntemi</h2>
        <div className="bos-durum">
          <p className="eyebrow">Kayıtlı ödeme yöntemi yok</p>
          <p>
            Ödeme altyapısı (iyzico) henüz bağlanmadı. Bağlandığında kart
            bilgileriniz bizde değil, ödeme sağlayıcısında saklanacak; burada
            yalnızca kartın son dört hanesi görünecek.
          </p>
        </div>
      </section>

      <section className="pano__bolum">
        <h2 className="pano__bolum-baslik">Projeyi destekleyin</h2>
        <p className="pano__lead">
          Abonelikten bağımsız olarak, tek seferlik destek paketleriyle katkıda
          bulunabilirsiniz.
        </p>
        <div className="fiyat-izgara">
          {DESTEK_PAKETLERI.map((paket) => (
            <article className="fiyat-karti" key={paket.slug}>
              <h3 className="fiyat-karti__ad">{paket.ad}</h3>
              <p className="fiyat-karti__tutar mono">{kurusBicimle(paket.fiyatKurus)}</p>
              <p className="fiyat-karti__aciklama">{paket.aciklama}</p>
              <button className="btn" type="button" disabled>
                Destek olun
              </button>
              <p className="pano__not">Ödeme altyapısı bağlanınca etkinleşecek.</p>
            </article>
          ))}
        </div>
        <p className="pano__not">
          Ayrıntılı karşılaştırma için <Link href="/fiyatlandirma">fiyatlandırma
          sayfasına</Link> bakabilirsiniz.
        </p>
      </section>
    </>
  );
}
