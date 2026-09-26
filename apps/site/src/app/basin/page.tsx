import { BASIN } from "@/data/kurumsal";
import { KURUM } from "@/data/kurum";
import { SayfaKabuk } from "@/components/SayfaKabuk";
import { sayfaMetadata } from "@/lib/seo";

export const metadata = sayfaMetadata({
  baslik: "Basın",
  aciklama: "Marka varlıkları ve kurumsal künye bilgileri.",
  yol: "/basin",
});

export default function BasinSayfasi() {
  return (
    <SayfaKabuk current="hakkimizda" ustBaslik="Kurum" baslik="Basın" lead={BASIN.lead}>
      <section className="section">
        <div className="page">
          <div className="section__head">
            <div>
              <h2>Marka varlıkları</h2>
            </div>
          </div>
          {BASIN.varliklar.length === 0 ? (
            <p className="section__lead">
              Varlık paketi hazırlanıyor. Bu arada görsel talepleriniz için bizimle
              iletişime geçebilirsiniz.
            </p>
          ) : (
            <ul className="liste">
              {BASIN.varliklar.map((v) => (
                <li key={v.href}>
                  <a href={v.href}>{v.ad}</a> — {v.not}
                </li>
              ))}
            </ul>
          )}
        </div>
      </section>

      <section className="section">
        <div className="page">
          <div className="section__head">
            <div>
              <h2>Kurumsal künye</h2>
            </div>
          </div>
          <dl className="kunye">
            <div>
              <dt>Ticari unvan</dt>
              <dd>{KURUM.unvan}</dd>
            </div>
            <div>
              <dt>Vergi dairesi / numarası</dt>
              <dd>
                {KURUM.vergiDairesi} / {KURUM.vergiNo}
              </dd>
            </div>
            <div>
              <dt>Adres</dt>
              <dd>{KURUM.adres}</dd>
            </div>
            <div>
              <dt>E-posta</dt>
              <dd>{KURUM.eposta}</dd>
            </div>
            <div>
              <dt>ETBİS kaydı</dt>
              <dd>{KURUM.etbis}</dd>
            </div>
          </dl>
        </div>
      </section>
    </SayfaKabuk>
  );
}
