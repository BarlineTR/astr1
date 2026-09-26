import Link from "next/link";

import { SITE } from "@/data/icerik";

export type PageId =
  | "ana"
  | "platform"
  | "cozumler"
  | "teknoloji"
  | "fiyatlandirma"
  | "hakkimizda"
  | "iletisim"
  | "panel";

/**
 * Bağlantı adresi tipi, `Link`'in kendi tipinden türetilir.
 *
 * `typedRoutes` açık: var olmayan bir adrese bağlantı derleme anında reddedilir
 * ve kurumsal bir sitede ölü iç bağlantı olmaması buna değer. Tipi Next'in
 * ürettiği dosyadan import etmek yerine buradan türetiyoruz — o dosyanın yolu
 * Next'in iç meselesi ve sürümle değişebilir.
 */
type Yol = React.ComponentProps<typeof Link>["href"];

/**
 * Gezinme: kurumsal ürün hiyerarşisi ve iletişim.
 *
 * İletişim buraya taşındı. Sağ tarafta eylem olarak durduğunda üç düğme yan
 * yana geliyordu ve hiçbiri diğerinden ayırt edilemiyordu; oysa İletişim bir
 * sayfa, Hesap ve Panel ise hesaba giden yollar.
 */
const NAV: ReadonlyArray<{ id: PageId; label: string; href: Yol }> = [
  { id: "platform", label: "Platform", href: "/platform" },
  { id: "cozumler", label: "Çözümler", href: "/cozumler" },
  { id: "teknoloji", label: "Teknoloji", href: "/teknoloji" },
  { id: "fiyatlandirma", label: "Fiyatlandırma", href: "/fiyatlandirma" },
  { id: "hakkimizda", label: "Hakkımızda", href: "/hakkimizda" },
  { id: "iletisim", label: "İletişim", href: "/iletisim" },
];

/**
 * Sağdaki iki eylem.
 *
 * Hesap ve Panel ayrı: biri hesabın kendisine (bilgiler, yetki), diğeri işin
 * yapıldığı yere (cihazlar) gider. Tek bir "Panel" düğmesi ikisini de
 * karşılıyormuş gibi duruyordu ama hesabına bakmak isteyen kullanıcı önce
 * cihaz listesine düşüyordu.
 *
 * İkisi de her zaman görünür ve şerit statik kalır. Oturuma göre değişen bir
 * başlık, bütün pazarlama sayfalarını dinamik hale getirir ve önbelleklenmesini
 * engellerdi; giriş yapmamış ziyaretçiyi zaten middleware girişe yolluyor.
 */
const HESAP: { label: string; href: Yol } = { label: "Hesap", href: "/panel/hesap" };
const PANEL: { label: string; href: Yol } = { label: "Panel", href: "/panel" };

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
          {/* Dar ekranda sağdaki sade eylem menüye iner. */}
          <Link className="site-nav__only-compact" href={HESAP.href}>
            {HESAP.label}
          </Link>
        </nav>

        <div className="site-header__eylemler">
          <Link className="btn btn--quiet" href={HESAP.href}>
            {HESAP.label}
          </Link>
          <Link
            className={
              current === "panel" ? "btn btn--console is-current" : "btn btn--console"
            }
            href={PANEL.href}
            aria-current={current === "panel" ? "page" : undefined}
          >
            {PANEL.label}
          </Link>
        </div>
      </div>
    </header>
  );
}
