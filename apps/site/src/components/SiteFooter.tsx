import Link from "next/link";

import { SITE } from "@/data/icerik";
import { KURUM } from "@/data/kurum";

/** Bkz. SiteHeader: adres tipi Link'in kendi tipinden türetilir. */
type Yol = React.ComponentProps<typeof Link>["href"];

const BOLUMLER: ReadonlyArray<{
  baslik: string;
  baglantilar: ReadonlyArray<readonly [string, Yol]>;
}> = [
  {
    baslik: "Ürün",
    baglantilar: [
      ["Platform", "/platform"],
      ["Çözümler", "/cozumler"],
      ["Teknoloji", "/teknoloji"],
      ["Fiyatlandırma", "/fiyatlandirma"],
    ],
  },
  {
    baslik: "Kurum",
    baglantilar: [
      ["Hakkımızda", "/hakkimizda"],
      ["Yönetim", "/hakkimizda/yonetim"],
      ["Basın", "/basin"],
      ["İletişim", "/iletisim"],
    ],
  },
  {
    baslik: "Hukuki",
    baglantilar: [
      ["KVKK aydınlatma", "/kvkk"],
      ["Gizlilik", "/gizlilik"],
      ["Çerezler", "/cerez"],
      ["Kullanım koşulları", "/kosullar"],
    ],
  },
];

export function SiteFooter() {
  const yil = new Date().getFullYear();

  return (
    <footer className="site-footer">
      <div className="page site-footer__inner">
        <div className="site-footer__grid">
          {BOLUMLER.map((bolum) => (
            <nav key={bolum.baslik} className="site-footer__col" aria-label={bolum.baslik}>
              <p className="site-footer__head">{bolum.baslik}</p>
              {bolum.baglantilar.map(([ad, href]) => (
                <Link key={ad} href={href}>
                  {ad}
                </Link>
              ))}
            </nav>
          ))}

          <nav className="site-footer__col" aria-label="Kaynak">
            <p className="site-footer__head">Kaynak</p>
            <a href={SITE.repoUrl} target="_blank" rel="noreferrer">
              Depo
            </a>
            <Link href="/platform/demo">Konsol demosu</Link>
          </nav>
        </div>

        <div className="site-footer__base">
          <p>
            © {yil} {KURUM.unvan}
          </p>

          {/*
            Yer tutucu kurum bilgisiyle yayına çıkmak fark edilmeden mümkün
            olmasın: bayrak kalkana kadar bu uyarı her sayfanın altında durur.
          */}
          {KURUM.YER_TUTUCU && (
            <p className="site-footer__uyari">
              Bu sayfadaki kurum bilgileri yer tutucudur — yayına hazır değildir.
            </p>
          )}
        </div>
      </div>
    </footer>
  );
}
