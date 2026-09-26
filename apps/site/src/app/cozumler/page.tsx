import Link from "next/link";

import { COZUMLER } from "@/data/cozumler";
import { SayfaKabuk } from "@/components/SayfaKabuk";

export const metadata = {
  title: "Çözümler",
  description:
    "Karşılama, bilgilendirme ve eğitim senaryolarında ASTRO sosyal robot platformu.",
};

export default function CozumlerSayfasi() {
  return (
    <SayfaKabuk
      current="cozumler"
      ustBaslik="Kullanım alanları"
      baslik="Çözümler"
      lead="Platformun hangi ortamda ne işe yaradığı — senaryoyla birlikte."
    >
      <section className="section">
        <div className="page">
          <div className="features">
            {COZUMLER.map((c) => (
              <article className="feature" key={c.slug}>
                <h2 className="feature__title">
                  <Link href={`/cozumler/${c.slug}`}>{c.ad}</Link>
                </h2>
                <p className="feature__body">{c.ozet}</p>
              </article>
            ))}
          </div>
        </div>
      </section>
    </SayfaKabuk>
  );
}
