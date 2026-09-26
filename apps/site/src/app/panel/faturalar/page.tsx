import { desc, eq } from "drizzle-orm";

import { db } from "@/db";
import { orders } from "@/db/schema";
import { KURUM } from "@/data/kurum";
import { kurusBicimle } from "@/lib/para";
import { oturumGerekli } from "@/lib/oturum";
import { sayfaMetadata } from "@/lib/seo";

export const metadata = sayfaMetadata({
  baslik: "Faturalar",
  aciklama: "Ödeme geçmişiniz ve faturalarınız.",
  yol: "/panel",
  dizinleme: false,
});

const DURUM_ADI: Record<string, string> = {
  odendi: "ödendi",
  bekliyor: "bekliyor",
  basarisiz: "başarısız",
  iade: "iade edildi",
};

export default async function FaturalarSayfasi() {
  const oturum = await oturumGerekli("/panel/faturalar");

  const siparisler = await db
    .select()
    .from(orders)
    .where(eq(orders.userId, oturum.user.id))
    .orderBy(desc(orders.createdAt));

  return (
    <>
      <div className="pano__baslik">
        <h1>Faturalar</h1>
        <p className="pano__lead">Ödeme geçmişiniz ve siparişleriniz.</p>
      </div>

      {siparisler.length === 0 ? (
        <div className="bos-durum">
          <p className="eyebrow">Henüz fatura yok</p>
          <p>
            İlk ödemeniz gerçekleştiğinde siparişleriniz burada listelenir.
          </p>
          <p className="bos-durum__not">
            Faturalar <strong>{oturum.user.email}</strong> adresine de gönderilir.
          </p>
        </div>
      ) : (
        <table className="teknik-tablo">
          <caption>Siparişleriniz</caption>
          <thead>
            <tr>
              <th scope="col">Tarih</th>
              <th scope="col">Sipariş</th>
              <th scope="col">Tutar</th>
              <th scope="col">Durum</th>
            </tr>
          </thead>
          <tbody>
            {siparisler.map((s) => (
              <tr key={s.id}>
                <th scope="row">
                  {s.createdAt.toLocaleDateString("tr-TR")}
                </th>
                <td className="mono">{s.id.slice(0, 8)}…</td>
                <td className="mono">{kurusBicimle(s.totalMinor)}</td>
                <td>{DURUM_ADI[s.status] ?? s.status}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <section className="pano__bolum">
        <h2 className="pano__bolum-baslik">Fatura bilgileri</h2>
        <dl className="kunye">
          <div>
            <dt>Fatura adı</dt>
            <dd>{oturum.user.name}</dd>
          </div>
          <div>
            <dt>E-posta</dt>
            <dd>{oturum.user.email}</dd>
          </div>
          <div>
            <dt>Kurum</dt>
            <dd>{(oturum.user as { company?: string | null }).company ?? "—"}</dd>
          </div>
        </dl>
        <p className="pano__not">
          Kurumsal fatura için vergi bilgilerinizi{" "}
          <a href={`mailto:${KURUM.eposta}`}>bize iletin</a>. Resmî fatura
          düzenlemesi, kurum bilgileri tamamlandığında devreye alınacak.
        </p>
      </section>
    </>
  );
}
