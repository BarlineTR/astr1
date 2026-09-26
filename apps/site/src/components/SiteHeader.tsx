import Link from "next/link";

import { SITE } from "@/data/icerik";

/**
 * Bağlantı adresi tipi, `Link`'in kendi tipinden türetilir.
 *
 * `typedRoutes` açık: var olmayan bir adrese bağlantı derleme anında reddedilir
 * ve kurumsal bir sitede ölü iç bağlantı olmaması buna değer. Tipi Next'in
 * ürettiği dosyadan import etmek yerine buradan türetiyoruz — o dosyanın yolu
 * Next'in iç meselesi ve sürümle değişebilir.
 */
type Yol = React.ComponentProps<typeof Link>["href"];

export type PageId =
  | "ana"
  | "platform"
  | "cozumler"
  | "teknoloji"
  | "fiyatlandirma"
  | "hakkimizda"
  | "iletisim"
  | "panel";

/** Kurumsal ürün hiyerarşisi: platform → çözüm → teknoloji → fiyat. */
const NAV: ReadonlyArray<{ id: PageId; label: string; href: Yol }> = [
  { id: "platform", label: "Platform", href: "/platform" },
  { id: "cozumler", label: "Çözümler", href: "/cozumler" },
  { id: "teknoloji", label: "Teknoloji", href: "/teknoloji" },
  { id: "fiyatlandirma", label: "Fiyatlandırma", href: "/fiyatlandirma" },
  { id: "hakkimizda", label: "Hakkımızda", href: "/hakkimizda" },
];

/** Panel gezinme bağlantısı değil, eylem. Şeritte çerçeveli ve bir tık büyük durur. */
const PANEL: { id: PageId; label: string; href: Yol } = {
  id: "panel",
  label: "Panel",
  href: "/panel",
};

/** Bütün sayfaların paylaştığı başlık şeridi. Etkin sayfa işaretlenir. */
export function SiteHeader({ current }: { current: PageId }) {
  return (
    <header className="site-header">
      <div className="page site-header__inner">
        <Link className="site-header__mark" href="/">
          {SITE.name}
          <span>{SITE.version}</span>
        </Link>

        {/*
          Dar ekranda açılır menü, geniş ekranda şerit — JavaScript olmadan.

          Önce <details> denendi ama tarayıcı içeriği ::details-content
          sarmalayıcısına alıyor ve kapalıyken kutu 0×0 kalıyor; `display` ile
          ezilemiyor, yani geniş ekranda gezinme görünmüyordu. Onay kutusu
          deseni bu sorunu hiç doğurmuyor ve klavyeyle çalışıyor.
        */}
        <input
          type="checkbox"
          id="site-menu-toggle"
          className="site-menu__toggle"
          aria-label="Menüyü aç kapat"
        />
        <label className="site-menu__button" htmlFor="site-menu-toggle">
          Menü
        </label>
        <nav className="site-nav" aria-label="Sayfalar">
          {NAV.map((item) => (
            <Link
              key={item.id}
              href={item.href}
              className={item.id === current ? "is-current" : undefined}
              aria-current={item.id === current ? "page" : undefined}
            >
              {item.label}
            </Link>
          ))}
          {/* Dar ekranda şeritten düşen bağlantı menüde kalır. */}
          <Link className="site-nav__only-compact" href="/iletisim">
            İletişim
          </Link>
        </nav>

        <Link className="btn btn--quiet" href="/iletisim">
          İletişim
        </Link>

        <Link
          className={
            current === PANEL.id ? "btn btn--console is-current" : "btn btn--console"
          }
          href={PANEL.href}
          aria-current={current === PANEL.id ? "page" : undefined}
        >
          {PANEL.label}
        </Link>
      </div>
    </header>
  );
}
