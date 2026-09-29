import Link from "next/link";

import { CikisDugmesi } from "@/components/CikisDugmesi";
import { PanoNav } from "@/components/PanoNav";
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
    <div className="pano">
      <header className="pano__ust">
        <div className="page pano__ust-ic">
          <Link className="site-header__mark" href="/">
            {SITE.name}
            <span>{SITE.version}</span>
          </Link>

          <PanoNav />

          <span className="pano__kullanici mono">{oturum.user.email}</span>
          <CikisDugmesi className="btn btn--quiet" />
        </div>
      </header>

      <main className="page pano__govde">{children}</main>
    </div>
  );
}
