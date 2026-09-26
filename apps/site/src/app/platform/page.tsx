import Link from "next/link";

import { FEATURES, SHOWCASE } from "@/data/icerik";
import { SayfaKabuk } from "@/components/SayfaKabuk";
import { TeknikTablo } from "@/components/TeknikTablo";
import { sayfaMetadata, breadcrumbJsonLd, productJsonLd } from "@/lib/seo";
import { JsonLd } from "@/components/JsonLd";

export const metadata = sayfaMetadata({
  baslik: "Platform",
  aciklama:
    "ASTRO V1: konuşana ve görünen kişiye dönen sosyal robot platformu. " +
    "Yetenekler, ölçülmüş çalışma sınırları ve teknik veriler.",
  yol: "/platform",
});

export default function PlatformSayfasi() {
  return (
    <>
      <JsonLd data={productJsonLd()} />
      <JsonLd
        data={breadcrumbJsonLd([
          { ad: "Ana sayfa", yol: "/" },
          { ad: "Platform", yol: "/platform" },
        ])}
      />
    <SayfaKabuk
      current="platform"
      ustBaslik="ASTRO V1"
      baslik="Platform"
      lead="Çevresindeki insanları gören, duyan ve kiminle ilgileneceğine kendi karar veren bir robot platformu."
    >
      <section className="section">
        <div className="page">
          <div className="section__head">
            <div>
              <h2>Algı ve karar</h2>
              <p className="section__lead">
                Robotun neyi algıladığı, nasıl karar verdiği ve nasıl hareket ettiği.
              </p>
            </div>
          </div>
          <div className="features">
            {SHOWCASE.map((adim) => (
              <article className="feature" key={adim.id}>
                <p className="eyebrow">{adim.label}</p>
                <h3 className="feature__title">{adim.title}</h3>
                <p className="feature__body">{adim.body}</p>
              </article>
            ))}
          </div>
        </div>
      </section>

      <section className="section" id="teknik">
        <div className="page">
          <div className="section__head">
            <div>
              <h2>Teknik veriler</h2>
              <p className="section__lead">
                Aşağıdaki değerlerin hepsi ölçülmüştür; tahmin edilen değer yoktur ve
                her birinin nereden geldiği yazılıdır.
              </p>
            </div>
          </div>
          <TeknikTablo />
        </div>
      </section>

      <section className="section">
        <div className="page">
          <div className="section__head">
            <div>
              <h2>Diğer yetenekler</h2>
            </div>
          </div>
          <div className="features">
            {FEATURES.map((f) => (
              <article className="feature" key={f.title}>
                <h3 className="feature__title">{f.title}</h3>
                <p className="feature__body">{f.body}</p>
              </article>
            ))}
          </div>
        </div>
      </section>

      <section className="section section--closing">
        <div className="page closing">
          <div>
            <h2>Konsolu deneyin</h2>
            <p className="section__lead">
              Kontrol konsolunun tarayıcı içinde koşan gösterimi; robota bağlanmaz,
              senaryoyu yerinde oynatır.
            </p>
          </div>
          <Link className="btn btn--primary" href="/platform/demo">
            Demoyu açın
          </Link>
        </div>
      </section>
    </SayfaKabuk>
    </>
  );
}
