import Link from "next/link";

import { CLOSING, FEATURES, FIGURES, HERO, SITE } from "@/data/icerik";
import { Belirenler } from "@/components/Belirenler";
import { Gosteri } from "@/components/Gosteri";
import { HeroBolum } from "@/components/HeroBolum";
import { SiteFooter } from "@/components/SiteFooter";
import { SiteHeader } from "@/components/SiteHeader";
import { JsonLd } from "@/components/JsonLd";
import { organizationJsonLd, productJsonLd, sayfaMetadata } from "@/lib/seo";

export const metadata = sayfaMetadata({
  baslik: "ASTRO — sosyal robot platformu",
  aciklama:
    "Çevresindeki insanları gören, duyan ve kiminle ilgileneceğine kendi karar " +
    "veren robot platformu. Karşılama, bilgilendirme ve etkileşim için.",
  yol: "/",
});

/**
 * Ana sayfa.
 *
 * Giriş ve özellik gösterisi birbirinden bağımsız iki bölümdür ve her birinin
 * kendi 3B sahnesi vardır.
 *
 * Tek bir yapışkan tuval paylaşıldığında iki sorun çıkıyordu: giriş metni ve
 * rakam şeridi yukarı kayarken sabit duran modelin ortasından geçiyor, ve
 * girişin sakin duruşu ile gösterinin kamera hareketi aynı sahneyi çekiştiriyordu.
 * Ayrı bölümler bunu yapısal olarak çözer.
 */
export default function AnaSayfa() {
  return (
    <>
      <JsonLd data={organizationJsonLd()} />
      <JsonLd data={productJsonLd()} />
      <SiteHeader current="ana" />

      <main>
        <HeroBolum>
          <div className="page hero__inner">
            <p className="eyebrow">{HERO.eyebrow}</p>
            <h1 className="hero__title">{HERO.title}</h1>
            <p className="hero__lead">{HERO.lead}</p>
            <div className="hero__actions">
              <Link className="btn btn--primary" href="/platform">
                Platformu inceleyin
              </Link>
              <Link className="btn" href="/iletisim">
                Teklif isteyin
              </Link>
            </div>
          </div>

          <div className="figures">
            <dl className="page figures__inner">
              {FIGURES.map((figure) => (
                <div className="figure" key={figure.label}>
                  <dt className="figures__label">{figure.label}</dt>
                  <dd className="figures__value mono">{figure.value}</dd>
                </div>
              ))}
            </dl>
          </div>
        </HeroBolum>

        <Gosteri />

        <Belirenler>
          <section className="section" id="diger">
            <div className="page">
              <div className="section__head">
                <h2>Diğer yetenekler</h2>
              </div>
              <div className="features">
                {FEATURES.map((feature, i) => (
                  <article
                    className="feature reveal"
                    key={feature.title}
                    style={{ ["--reveal-delay" as string]: `${Math.min(i, 3) * 70}ms` }}
                  >
                    <h3 className="feature__title">{feature.title}</h3>
                    <p className="feature__body">{feature.body}</p>
                  </article>
                ))}
              </div>
            </div>
          </section>

          <section className="section section--closing reveal">
            <div className="page closing">
              <div>
                <h2>{CLOSING.title}</h2>
                <p className="section__lead">{CLOSING.lead}</p>
              </div>
              <a
                className="btn btn--primary"
                href={SITE.repoUrl}
                target="_blank"
                rel="noreferrer"
              >
                {CLOSING.action}
              </a>
            </div>
          </section>
        </Belirenler>
      </main>

      <SiteFooter />
    </>
  );
}
