import { FIGURES, HERO } from "@/data/icerik";

/**
 * Ana sayfa — bu aşamada yalnızca giriş metni ve rakam şeridi.
 *
 * Sunucu bileşeni: metnin tamamı ham HTML yanıtında bulunur. Taşımadan önce
 * gövde `<div id="app"></div>` idi ve bütün içerik tarayıcıda çiziliyordu.
 */
export default function AnaSayfa() {
  return (
    <main>
      <section className="hero is-settled">
        <div className="page hero__inner">
          <p className="eyebrow">{HERO.eyebrow}</p>
          <h1 className="hero__title">{HERO.title}</h1>
          <p className="hero__lead">{HERO.lead}</p>
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
      </section>
    </main>
  );
}
