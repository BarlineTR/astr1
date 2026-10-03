import { SayfaKabuk } from "@/components/SayfaKabuk";
import { RobotDurumuBolumu } from "@/components/RobotDurumuBolumu";
import { sayfaMetadata, breadcrumbJsonLd } from "@/lib/seo";
import { JsonLd } from "@/components/JsonLd";

export const metadata = sayfaMetadata({
  baslik: "Robot Durumu ve Stabilite",
  aciklama:
    "ASTRO V1 çalışan donanım aksamları, 50 Hz kapalı çevrim kontrol stabilitesi, " +
    "ölçülmüş hata toleransları ve donanımsal güvenlik katmanları.",
  yol: "/durum",
});

/**
 * Robot Durumu ve Stabilite Sayfası.
 *
 * Çalışan tüm donanım aksamlarını, 50 Hz kapalı çevrim kontrol stabilitesini,
 * firmware seviyesi güvenlik katmanlarını ve ölçülmüş çalışma parametrelerini
 * müstakil bir sayfada sergiler.
 */
export default function DurumSayfasi() {
  return (
    <>
      <JsonLd
        data={breadcrumbJsonLd([
          { ad: "Ana sayfa", yol: "/" },
          { ad: "Robot Durumu", yol: "/durum" },
        ])}
      />
      <SayfaKabuk
        current="durum"
        ustBaslik="Telemetri & Donanım"
        baslik="Robot Durumu ve Stabilite"
        lead="Çevresini gören, duyan ve karar veren ASTRO platformunun anlık çalışan donanım aksamları, kontrol döngüsü kararlılığı ve donanımsal güvenlik mimarisi."
      >
        <RobotDurumuBolumu />
      </SayfaKabuk>
    </>
  );
}
