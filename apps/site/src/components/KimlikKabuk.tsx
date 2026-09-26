import Link from "next/link";

import { SITE } from "@/data/icerik";

/**
 * Giriş ve kayıt sayfalarının kabuğu.
 *
 * Şerit ve alt bilgi yok: bu sayfalarda tek bir iş var ve gezinme dikkat
 * dağıtıyor. Marka logosu ana sayfaya dönüş yolu olarak duruyor.
 */
export function KimlikKabuk({
  baslik,
  lead,
  children,
  altYazi,
}: {
  baslik: string;
  lead: string;
  children: React.ReactNode;
  altYazi: React.ReactNode;
}) {
  return (
    <main className="kimlik">
      <div className="kimlik__kutu">
        <Link className="site-header__mark kimlik__mark" href="/">
          {SITE.name}
          <span>{SITE.version}</span>
        </Link>

        <h1 className="kimlik__baslik">{baslik}</h1>
        <p className="kimlik__lead">{lead}</p>

        {children}

        <p className="kimlik__alt">{altYazi}</p>
      </div>
    </main>
  );
}
