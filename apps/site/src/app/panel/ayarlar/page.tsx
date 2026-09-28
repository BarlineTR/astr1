import Link from "next/link";
import fs from "node:fs";
import path from "node:path";
import { robotAyarlariGetir } from "@/db/sorgular/ayarlar";
import { kullanicininCihazlari } from "@/db/sorgular/cihaz";
import { oturumGerekli } from "@/lib/oturum";
import { sayfaMetadata } from "@/lib/seo";
import { RobotAyarlariFormu } from "@/components/RobotAyarlariFormu";
import { BiliselHafizaKutusu } from "@/components/BiliselHafizaKutusu";

export const metadata = sayfaMetadata({
  baslik: "Robot Ayarları & Ses/Kişilik",
  aciklama: "Robotun ses tonu, selamlama metni ve alarm yapılandırması.",
  yol: "/panel",
  dizinleme: false,
});

function hafizaYukle() {
  const candidatePaths = [
    path.resolve(process.cwd(), "../../ros2_ws/astro_memory.json"),
    "/home/okistech/Desktop/astr1/ros2_ws/astro_memory.json",
  ];
  for (const p of candidatePaths) {
    try {
      if (fs.existsSync(p)) {
        return JSON.parse(fs.readFileSync(p, "utf-8"));
      }
    } catch {
      // yoksay
    }
  }
  return null;
}

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
  const hafiza = hafizaYukle();

  return (
    <>
      <div className="pano__baslik">
        <h1>Robot Ayarları & Karakter</h1>
        <p className="pano__lead">
          <strong className="mono">{aktifCihaz.name}</strong> ({aktifCihaz.serial}) için ses, selamlama ve güvenlik parametreleri.
        </p>
      </div>

      <RobotAyarlariFormu ayarlar={ayarlar} />

      <BiliselHafizaKutusu hafiza={hafiza} />
    </>
  );
}
