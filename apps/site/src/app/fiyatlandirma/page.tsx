import Link from "next/link";

import { DESTEK_PAKETLERI, GELISTIRME_FIYATI, PLANLAR, type Kalem } from "@/data/fiyatlar";
import { kurusBicimle } from "@/lib/para";
import { SayfaKabuk } from "@/components/SayfaKabuk";
import { sayfaMetadata } from "@/lib/seo";

export const metadata = sayfaMetadata({
  baslik: "Fiyatlandırma",
  aciklama: "Uzaktan erişim planları ve destek paketleri.",
  yol: "/fiyatlandirma",
});

export default function FiyatlandirmaSayfasi() {
  return (
    <SayfaKabuk
      current="fiyatlandirma"
      ustBaslik="Planlar"
      baslik="Fiyatlandırma"
      lead="Uzaktan erişim planları ve projeyi destekleme seçenekleri."
    >
      {/*
        Uydurma tutarla yayına çıkmak fark edilmeden mümkün olmasın:
        bayrak kalkana kadar bu uyarı sayfanın en üstünde durur.
      */}
      {GELISTIRME_FIYATI && (
        <section className="page">
          <p className="uyari-serit" role="status">
            Bu sayfadaki tutarlar geliştirme aşaması değerleridir; gerçek fiyat listesi
            değildir.
          </p>
        </section>
      )}

      <section className="section">
        <div className="page">
          <div className="section__head">
            <div>
              <h2>Uzaktan erişim planları</h2>
              <p className="section__lead">
                Robotun durumunu dış ağdan izlemek ve yönlendirmek için. Erişim paneli
                hazırlanıyor.
              </p>
            </div>
          </div>
          <div className="fiyat-izgara">
            {PLANLAR.map((p) => (
              <FiyatKarti kalem={p} key={p.slug} />
            ))}
          </div>
        </div>
      </section>

      <section className="section">
        <div className="page">
          <div className="section__head">
            <div>
              <h2>Destek paketleri</h2>
              <p className="section__lead">
                Projeyi sürdürmemize katkıda bulunmak isterseniz. Karşılığında adınız
                destekçiler listesinde görünür ve isterseniz fatura düzenlenir.
              </p>
            </div>
          </div>
          <div className="fiyat-izgara">
            {DESTEK_PAKETLERI.map((p) => (
              <FiyatKarti kalem={p} key={p.slug} />
            ))}
          </div>
        </div>
      </section>

      <section className="section section--closing">
        <div className="page closing">
          <div>
            <h2>Kurumsal kullanım</h2>
            <p className="section__lead">
              Birden çok robot, özel entegrasyon veya yerinde kurulum için teklif
              hazırlıyoruz.
            </p>
          </div>
          <Link className="btn btn--primary" href="/iletisim">
            Teklif isteyin
          </Link>
        </div>
      </section>
    </SayfaKabuk>
  );
}

function FiyatKarti({ kalem }: { kalem: Kalem }) {
  return (
    <article className="fiyat-karti">
      <h3 className="fiyat-karti__ad">{kalem.ad}</h3>
      <p className="fiyat-karti__tutar mono">
        {kurusBicimle(kalem.fiyatKurus)}
        {kalem.periyot === "ay" && <span className="fiyat-karti__periyot"> / ay</span>}
      </p>
      <p className="fiyat-karti__aciklama">{kalem.aciklama}</p>
      {kalem.ozellikler && (
        <ul className="liste">
          {kalem.ozellikler.map((o) => (
            <li key={o}>{o}</li>
          ))}
        </ul>
      )}
    </article>
  );
}
