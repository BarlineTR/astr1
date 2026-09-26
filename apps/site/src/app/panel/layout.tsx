import Link from "next/link";

import { CikisDugmesi } from "@/components/CikisDugmesi";
import { SITE } from "@/data/icerik";
import { oturumGerekli } from "@/lib/oturum";

/**
 * Panel kabuğu.
 *
 * Oturum burada doğrulanıyor: middleware yalnızca çerezin varlığına bakıyor,
 * geçerliliği bu katmanda kesinleşiyor. Panel altındaki her sayfa bu düzenden
 * geçtiği için kontrol tek yerde duruyor.
 */
export default async function PanelDuzeni({ children }: { children: React.ReactNode }) {
  const oturum = await oturumGerekli();

  return (
    <div className="panel">
      <header className="panel__ust">
        <div className="page panel__ust-ic">
          <Link className="site-header__mark" href="/">
            {SITE.name}
            <span>{SITE.version}</span>
          </Link>

          <nav className="panel__nav" aria-label="Panel">
            <Link href="/panel">Cihazlar</Link>
            <Link href="/panel/hesap">Hesap</Link>
          </nav>

          <span className="panel__kullanici mono">{oturum.user.email}</span>
          <CikisDugmesi className="btn btn--quiet" />
        </div>
      </header>

      <main className="page panel__govde">{children}</main>
    </div>
  );
}
