import { notFound } from "next/navigation";

import { COZUMLER, cozumBul } from "@/data/cozumler";
import { SayfaKabuk } from "@/components/SayfaKabuk";

/** Üç sektörün üçü de derleme anında üretilir; istek anında iş yapılmaz. */
export function generateStaticParams() {
  return COZUMLER.map((c) => ({ sektor: c.slug }));
}

export async function generateMetadata({ params }: PageProps<"/cozumler/[sektor]">) {
  const { sektor } = await params;
  const cozum = cozumBul(sektor);
  if (!cozum) return {};
  return { title: cozum.ad, description: cozum.ozet };
}

export default async function CozumSayfasi({ params }: PageProps<"/cozumler/[sektor]">) {
  const { sektor } = await params;
  const cozum = cozumBul(sektor);
  if (!cozum) notFound();

  return (
    <SayfaKabuk
      current="cozumler"
      ustBaslik="Çözüm"
      baslik={cozum.ad}
      lead={cozum.ozet}
    >
      <section className="section">
        <div className="page">
          <div className="section__head">
            <div>
              <h2>Senaryo</h2>
            </div>
          </div>
          <ol className="liste liste--numarali">
            {cozum.senaryo.map((adim) => (
              <li key={adim}>{adim}</li>
            ))}
          </ol>
        </div>
      </section>

      <section className="section">
        <div className="page">
          <div className="section__head">
            <div>
              <h2>Ne kazandırır</h2>
            </div>
          </div>
          <ul className="liste">
            {cozum.kazanc.map((k) => (
              <li key={k}>{k}</li>
            ))}
          </ul>
        </div>
      </section>
    </SayfaKabuk>
  );
}
