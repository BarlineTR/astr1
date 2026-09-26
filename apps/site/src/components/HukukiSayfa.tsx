import { notFound } from "next/navigation";

import { HUKUKI_METINLER, HUKUKI_YER_TUTUCU } from "@/data/hukuki";
import { SayfaKabuk } from "@/components/SayfaKabuk";
import { sayfaMetadata } from "@/lib/seo";

export function hukukiMetadata(slug: string) {
  const metin = HUKUKI_METINLER[slug];
  if (!metin) return {};
  return sayfaMetadata({
    baslik: metin.baslik,
    aciklama: `${metin.baslik} — ASTRO`,
    yol: `/${slug}`,
  });
}

/**
 * Hukuki metin sayfası.
 *
 * Metinlerin hukukçu onayından geçmediği sayfanın kendi üstünde yazıyor ve
 * `HUKUKI_YER_TUTUCU` bayrağı kalkana kadar orada kalıyor: onaysız bir metnin
 * yayında olduğu gizlenmemeli.
 *
 * Sürüm numarası görünür, çünkü onay kayıtları ona referans veriyor; sürüm
 * görünmezse kullanıcı neyi onayladığını sonradan bulamaz.
 */
export function HukukiSayfa({ slug }: { slug: string }) {
  const metin = HUKUKI_METINLER[slug];
  if (!metin) notFound();

  return (
    <SayfaKabuk
      current="hakkimizda"
      ustBaslik="Hukuki"
      baslik={metin.baslik}
      lead={`Sürüm: ${metin.surum}`}
    >
      <section className="section">
        <div className="page hukuki">
          {HUKUKI_YER_TUTUCU && (
            <p className="uyari-serit" role="alert">
              Bu metin taslaktır ve hukukçu onayından geçmemiştir. Bağlayıcı bir
              belge olarak kullanılmamalıdır.
            </p>
          )}

          {metin.bolumler.map((bolum, i) => (
            <section key={bolum.baslik}>
              <h2>
                <span className="hukuki__no mono">{String(i + 1)}.</span> {bolum.baslik}
              </h2>
              {bolum.paragraflar.map((p) => (
                <p key={p}>{p}</p>
              ))}
            </section>
          ))}
        </div>
      </section>
    </SayfaKabuk>
  );
}
