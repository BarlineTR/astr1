import type { PageId } from "./SiteHeader";
import { SiteFooter } from "./SiteFooter";
import { SiteHeader } from "./SiteHeader";

/**
 * İç sayfaların ortak kabuğu: şerit, başlık bloğu, gövde, alt bilgi.
 *
 * Başlık bloğu sunucu bileşeni olarak çizilir — `h1` ve giriş paragrafı her
 * sayfanın ham HTML yanıtında bulunmak zorunda.
 */
export function SayfaKabuk({
  current,
  ustBaslik,
  baslik,
  lead,
  children,
}: {
  current: PageId;
  ustBaslik?: string;
  baslik: string;
  lead?: string;
  children: React.ReactNode;
}) {
  return (
    <>
      <SiteHeader current={current} />
      <main>
        <section className="sayfa-giris">
          <div className="page">
            {ustBaslik && <p className="eyebrow">{ustBaslik}</p>}
            <h1 className="sayfa-giris__baslik">{baslik}</h1>
            {lead && <p className="sayfa-giris__lead">{lead}</p>}
          </div>
        </section>
        {children}
      </main>
      <SiteFooter />
    </>
  );
}
