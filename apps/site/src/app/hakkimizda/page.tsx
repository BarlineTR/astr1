import { ABOUT } from "@/data/icerik";
import { SayfaKabuk } from "@/components/SayfaKabuk";
import { sayfaMetadata } from "@/lib/seo";

export const metadata = sayfaMetadata({
  baslik: "Hakkımızda",
  aciklama:
    "İnsanla makine arasındaki etkileşimi ekrana dokunmaktan çıkarıp doğal olana " +
    "yaklaştırmaya çalışıyoruz.",
  yol: "/hakkimizda",
});

export default function HakkimizdaSayfasi() {
  return (
    <SayfaKabuk current="hakkimizda" ustBaslik="Kurum" baslik="Hakkımızda" lead={ABOUT.lead}>
      {ABOUT.sections.map((bolum, i) => (
        <section className="section" id={bolum.id} key={bolum.id}>
          <div className="page">
            <div className="section__head">
              <div className="section__index">{String(i + 1).padStart(2, "0")}</div>
              <div>
                <h2>{bolum.title}</h2>
                {"paragraphs" in bolum &&
                  bolum.paragraphs.map((p) => (
                    <p className="section__lead" key={p}>
                      {p}
                    </p>
                  ))}
                {"items" in bolum && (
                  <ul className="liste">
                    {bolum.items.map((x) => (
                      <li key={x}>{x}</li>
                    ))}
                  </ul>
                )}
              </div>
            </div>
          </div>
        </section>
      ))}
    </SayfaKabuk>
  );
}
