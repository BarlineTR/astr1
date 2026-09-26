import { YONETIM } from "@/data/kurumsal";
import { SayfaKabuk } from "@/components/SayfaKabuk";

export const metadata = {
  title: "Yönetim",
  description: "ASTRO'yu geliştiren ekip.",
};

export default function YonetimSayfasi() {
  return (
    <SayfaKabuk
      current="hakkimizda"
      ustBaslik="Kurum"
      baslik="Yönetim"
      lead="Donanım tasarımı, gömülü yazılım, algı ve etkileşim tasarımı aynı masada yürüyor."
    >
      <section className="section">
        <div className="page">
          {YONETIM.length === 0 ? (
            /*
              Liste boş: uydurma isim yazmak yerine eksik olduğunu söylüyoruz.
              Yanlış bir isim yayına çıkmaktansa boşluk görünür kalsın.
            */
            <p className="section__lead">
              Ekip bilgileri yakında bu sayfada yayımlanacak.
            </p>
          ) : (
            <div className="features">
              {YONETIM.map((kisi) => (
                <article className="feature" key={kisi.ad}>
                  <h2 className="feature__title">{kisi.ad}</h2>
                  <p className="eyebrow">{kisi.unvan}</p>
                  <p className="feature__body">{kisi.tanitim}</p>
                </article>
              ))}
            </div>
          )}
        </div>
      </section>
    </SayfaKabuk>
  );
}
