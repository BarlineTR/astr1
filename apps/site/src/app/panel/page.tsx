import { eq } from "drizzle-orm";
import Link from "next/link";

import { db } from "@/db";
import { devices } from "@/db/schema";
import { oturumGerekli } from "@/lib/oturum";
import { sayfaMetadata } from "@/lib/seo";

export const metadata = sayfaMetadata({
  baslik: "Cihazlar",
  aciklama: "Bağlı robotlarınız.",
  yol: "/panel",
  dizinleme: false,
});

/** Durum kodları kullanıcıya okunur hâlde gösterilir. */
const DURUM_ADI: Record<string, string> = {
  kayitli: "kayıtlı",
  "eslestirme-bekliyor": "eşleştirme bekliyor",
  cevrimdisi: "çevrimdışı",
  cevrimici: "çevrimiçi",
};

export default async function PanelAnaSayfa() {
  const oturum = await oturumGerekli();

  const cihazlar = await db
    .select()
    .from(devices)
    .where(eq(devices.ownerUserId, oturum.user.id));

  return (
    <>
      <div className="pano__baslik pano__baslik--eylemli">
        <div>
          <h1>Cihazlar</h1>
          <p className="pano__lead">Hesabınıza bağlı robotlar ve anlık durumları.</p>
        </div>
        <Link className="btn btn--primary" href="/panel/cihaz/ekle">
          Robot ekle
        </Link>
      </div>

      {cihazlar.length === 0 ? (
        /*
          Boş durum ne olduğunu anlatıyor. Boş bir liste göstermek kullanıcıya
          bir şeyin bozuk olduğunu düşündürüyordu.
        */
        <div className="bos-durum">
          <p className="eyebrow">Henüz cihaz yok</p>
          <p>
            Hesabınıza bağlı bir robot bulunmuyor. Robotu ekleyip eşleştirme kodu
            alabilirsiniz; ajanın bağlanması uzaktan erişim ağ geçidiyle gelecek.
          </p>
          <p>
            <Link className="btn btn--primary" href="/panel/cihaz/ekle">
              İlk robotunuzu ekleyin
            </Link>
          </p>
          <p className="bos-durum__not">
            Bu arada <Link href="/platform/demo">konsol demosunu</Link> inceleyebilir,
            kurumsal kullanım için <Link href="/iletisim">bize yazabilirsiniz</Link>.
          </p>
        </div>
      ) : (
        <ul className="cihaz-listesi">
          {cihazlar.map((c) => (
            <li className="cihaz" key={c.id}>
              <div>
                <h2 className="cihaz__ad">
                  <Link href={`/panel/cihaz/${c.id}`}>{c.name}</Link>
                </h2>
                <p className="cihaz__seri mono">{c.serial}</p>
              </div>
              <span className="cihaz__durum">{DURUM_ADI[c.status] ?? c.status}</span>
            </li>
          ))}
        </ul>
      )}
    </>
  );
}
