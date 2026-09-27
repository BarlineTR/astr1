import Link from "next/link";
import { cihazinNoktalari } from "@/db/sorgular/harita";
import { kullanicininCihazlari } from "@/db/sorgular/cihaz";
import { oturumGerekli } from "@/lib/oturum";
import { sayfaMetadata } from "@/lib/seo";
import { LidarHarita } from "@/components/LidarHarita";

export const metadata = sayfaMetadata({
  baslik: "LiDAR Harita & Devriye",
  aciklama: "Robotun bulunduğu ortam krokisi ve devriye noktaları.",
  yol: "/panel",
  dizinleme: false,
});

export default async function HaritaSayfasi() {
  const oturum = await oturumGerekli("/panel/harita");
  const cihazlar = await kullanicininCihazlari(oturum.user.id);

  if (cihazlar.length === 0) {
    return (
      <div className="bos-durum">
        <p className="eyebrow">Bağlı robot bulunamadı</p>
        <p>Harita ve devriye yönetimi için robotunuzu bağlayın.</p>
        <p>
          <Link className="btn btn--primary" href="/panel/cihaz/ekle">
            Robot ekle
          </Link>
        </p>
      </div>
    );
  }

  const aktifCihaz = cihazlar[0];
  if (!aktifCihaz) {
    return null;
  }
  const noktalar = await cihazinNoktalari(aktifCihaz.id);

  return (
    <>
      <div className="pano__baslik">
        <h1>LiDAR Haritası & Devriye Yönetimi</h1>
        <p className="pano__lead">
          <strong className="mono">{aktifCihaz.name}</strong> ({aktifCihaz.serial}) LiDAR radarından alınan 2D ortam krokisi ve belirlenen devriye hedefleri.
        </p>
      </div>

      <LidarHarita deviceId={aktifCihaz.id} noktalar={noktalar} />
    </>
  );
}
