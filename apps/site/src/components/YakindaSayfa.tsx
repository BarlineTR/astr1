import type { PageId } from "./SiteHeader";
import { SiteFooter } from "./SiteFooter";
import { SiteHeader } from "./SiteHeader";

/**
 * Henüz yazılmamış bir sayfanın dürüst hali.
 *
 * Rota gerçekten var olmak zorunda: `typedRoutes` var olmayan bir adrese
 * bağlantıyı derleme anında reddediyor ve bu koruma tutulmaya değer. Sayfa da
 * boş bir kabuk göstermek yerine ne olacağını söyler — ziyaretçi bir şeyin
 * bozuk olduğunu düşünmesin.
 */
export function YakindaSayfa({
  current,
  baslik,
  aciklama,
}: {
  current: PageId;
  baslik: string;
  aciklama: string;
}) {
  return (
    <>
      <SiteHeader current={current} />
      <main>
        <section className="section">
          <div className="page">
            <div className="section__head">
              <div>
                <p className="eyebrow">Hazırlanıyor</p>
                <h1>{baslik}</h1>
                <p className="section__lead">{aciklama}</p>
              </div>
            </div>
          </div>
        </section>
      </main>
      <SiteFooter />
    </>
  );
}
