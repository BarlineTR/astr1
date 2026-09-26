import { IletisimFormu } from "@/components/IletisimFormu";
import { KURUM } from "@/data/kurum";
import { SayfaKabuk } from "@/components/SayfaKabuk";
import { sayfaMetadata } from "@/lib/seo";

export const metadata = sayfaMetadata({
  baslik: "İletişim",
  aciklama:
    "Sorular, iş birliği ve kurumsal teklif talepleri için bize ulaşın.",
  yol: "/iletisim",
});

export default function IletisimSayfasi() {
  return (
    <SayfaKabuk
      current="iletisim"
      ustBaslik="Bize ulaşın"
      baslik="İletişim"
      lead="Proje hakkındaki sorular, iş birliği önerileri ve kurumsal teklif talepleri."
    >
      <section className="section">
        <div className="page iletisim-izgara">
          <div>
            <h2>Soru ve iş birliği</h2>
            <p className="section__lead">
              Platform, teknoloji ya da iş birliği hakkında bir sorunuz varsa yazın.
            </p>
            <IletisimFormu tur="iletisim" />
          </div>

          <div id="teklif">
            <h2>Kurumsal teklif</h2>
            <p className="section__lead">
              Birden çok robot, özel entegrasyon veya yerinde kurulum için teklif
              hazırlıyoruz. Kurum adı ve ihtiyacınızı yazmanız yeterli.
            </p>
            <IletisimFormu tur="teklif" />
          </div>
        </div>
      </section>

      <section className="section">
        <div className="page">
          <div className="section__head">
            <div>
              <h2>Kurumsal bilgiler</h2>
            </div>
          </div>
          <dl className="kunye">
            <div>
              <dt>Ticari unvan</dt>
              <dd>{KURUM.unvan}</dd>
            </div>
            <div>
              <dt>E-posta</dt>
              <dd>{KURUM.eposta}</dd>
            </div>
            <div>
              <dt>Telefon</dt>
              <dd>{KURUM.telefon}</dd>
            </div>
            <div>
              <dt>Adres</dt>
              <dd>{KURUM.adres}</dd>
            </div>
          </dl>
        </div>
      </section>
    </SayfaKabuk>
  );
}
