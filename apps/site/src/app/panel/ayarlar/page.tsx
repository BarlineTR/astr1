import Link from "next/link";
import { robotAyarlariGetir } from "@/db/sorgular/ayarlar";
import { kullanicininCihazlari } from "@/db/sorgular/cihaz";
import { oturumGerekli } from "@/lib/oturum";
import { sayfaMetadata } from "@/lib/seo";
import { RobotAyarlariFormu } from "@/components/RobotAyarlariFormu";

export const metadata = sayfaMetadata({
  baslik: "Robot Ayarları & Ses/Kişilik",
  aciklama: "Robotun ses tonu, selamlama metni ve alarm yapılandırması.",
  yol: "/panel",
  dizinleme: false,
});

export default async function AyarlarSayfasi() {
  const oturum = await oturumGerekli("/panel/ayarlar");
  const cihazlar = await kullanicininCihazlari(oturum.user.id);

  if (cihazlar.length === 0) {
    return (
      <div className="bos-durum">
        <p className="eyebrow">Bağlı robot bulunamadı</p>
        <p>Ayar yapabilmek için hesabınıza en az bir robot eşleştirmiş olmanız gerekir.</p>
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
  const ayarlar = await robotAyarlariGetir(aktifCihaz.id);

  return (
    <>
      <div className="pano__baslik">
        <h1>Robot Ayarları & Karakter</h1>
        <p className="pano__lead">
          <strong className="mono">{aktifCihaz.name}</strong> ({aktifCihaz.serial}) için ses, selamlama ve güvenlik parametreleri.
        </p>
      </div>

      <RobotAyarlariFormu ayarlar={ayarlar} />
    </>
  );
}
