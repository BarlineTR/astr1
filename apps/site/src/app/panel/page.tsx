import { eq } from "drizzle-orm";

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

export default async function PanelAnaSayfa() {
  const oturum = await oturumGerekli();

  const cihazlar = await db
    .select()
    .from(devices)
    .where(eq(devices.ownerUserId, oturum.user.id));

  return (
    <>
      <div className="panel__baslik">
        <h1>Cihazlar</h1>
        <p className="panel__lead">
          Hesabınıza bağlı robotlar ve anlık durumları.
        </p>
      </div>

      {cihazlar.length === 0 ? (
        /*
          Boş durum ne olduğunu anlatıyor. Boş bir liste göstermek kullanıcıya
          bir şeyin bozuk olduğunu düşündürüyordu.
        */
        <div className="bos-durum">
          <p className="eyebrow">Henüz cihaz yok</p>
          <p>
            Hesabınıza bağlı bir robot bulunmuyor. Uzaktan erişim ağ geçidi
            hazırlanıyor; hazır olduğunda cihazınızı buradan eşleştireceksiniz.
          </p>
          <p className="bos-durum__not">
            Bu arada <a href="/platform/demo">konsol demosunu</a> inceleyebilir,
            kurumsal kullanım için <a href="/iletisim">bize yazabilirsiniz</a>.
          </p>
        </div>
      ) : (
        <ul className="cihaz-listesi">
          {cihazlar.map((c) => (
            <li className="cihaz" key={c.id}>
              <div>
                <h2 className="cihaz__ad">{c.name}</h2>
                <p className="cihaz__seri mono">{c.serial}</p>
              </div>
              <span className="cihaz__durum">{c.status}</span>
            </li>
          ))}
        </ul>
      )}
    </>
  );
}
