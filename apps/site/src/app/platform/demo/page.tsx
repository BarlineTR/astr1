import { Konsol } from "@/components/Konsol";
import { SayfaKabuk } from "@/components/SayfaKabuk";
import { sayfaMetadata } from "@/lib/seo";

export const metadata = sayfaMetadata({
  baslik: "Konsol demosu",
  aciklama:
    "ASTRO kontrol konsolunun tarayıcı içinde koşan gösterimi. Robota bağlanmaz.",
  yol: "/platform/demo",
});

/**
 * Genel demo.
 *
 * Tarayıcı içi senaryoyla çalışır ve robota hiç bağlanmaz; bu yüzden herkese
 * açık kalabiliyor. Gerçek konsol `/panel/cihaz/[id]` altında, giriş ve cihaz
 * yetkisi arkasında.
 */
export default function DemoSayfasi() {
  return (
    <SayfaKabuk
      current="platform"
      ustBaslik="Platform"
      baslik="Konsol demosu"
      lead="Kontrol konsolunun tarayıcınızda koşan gösterimi. Gerçek bir robota bağlanmaz ve komut arayüzü içermez."
    >
      <section className="section section--flush">
        <div className="page">
          <Konsol mod="demo" />
        </div>
      </section>
    </SayfaKabuk>
  );
}
