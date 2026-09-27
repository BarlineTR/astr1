import Link from "next/link";
import { eq } from "drizzle-orm";

import { db } from "@/db";
import { orderItems, orders } from "@/db/schema";
import { kurusBicimle } from "@/lib/para";
import { SayfaKabuk } from "@/components/SayfaKabuk";
import { sayfaMetadata } from "@/lib/seo";

export const metadata = sayfaMetadata({
  baslik: "Ödeme sonucu",
  aciklama: "Siparişinizin durumu.",
  yol: "/odeme/sonuc",
  dizinleme: false,
});

const DURUM_BASLIK: Record<string, string> = {
  odendi: "Ödeme alındı",
  bekliyor: "Ödeme bekleniyor",
  basarisiz: "Ödeme tamamlanamadı",
  iade: "İade edildi",
};

export default async function OdemeSonucSayfasi({
  params,
}: PageProps<"/odeme/sonuc/[siparisId]">) {
  const { siparisId } = await params;

  const [siparis] =
    siparisId === "bilinmiyor"
      ? []
      : await db.select().from(orders).where(eq(orders.id, siparisId)).limit(1);

  if (!siparis) {
    return (
      <SayfaKabuk
        current="fiyatlandirma"
        ustBaslik="Ödeme"
        baslik="Sipariş bulunamadı"
        lead="Bu ödeme oturumuna ait bir sipariş bulamadık."
      >
        <section className="section">
          <div className="page">
            <p className="section__lead">
              Kartınızdan çekim yapıldıysa lütfen bizimle iletişime geçin; kayıt
              numaranızı bulup durumu netleştirelim.
            </p>
            <Link className="btn btn--primary" href="/iletisim">
              İletişime geçin
            </Link>
          </div>
        </section>
      </SayfaKabuk>
    );
  }

  const kalemler = await db
    .select()
    .from(orderItems)
    .where(eq(orderItems.orderId, siparis.id));

  const basarili = siparis.status === "odendi";

  return (
    <SayfaKabuk
      current="fiyatlandirma"
      ustBaslik="Ödeme Sonucu"
      baslik={basarili ? "Ödemeniz Başarıyla Alındı!" : (DURUM_BASLIK[siparis.status] ?? "Sipariş durumu")}
      lead={
        basarili
          ? `Tebrikler! İşleminiz onaylandı. Detaylı sipariş ve fatura dökümü ${siparis.email} adresine gönderildi.`
          : "Ödeme tamamlanamadı. Kartınızdan çekim yapılmadıysa yeniden deneyebilirsiniz."
      }
    >
      <section className="section">
        <div className="page">
          {basarili && (
            <div
              className="panel"
              style={{
                backgroundColor: "rgba(16, 185, 129, 0.08)",
                border: "1px solid rgba(16, 185, 129, 0.3)",
                padding: "1.5rem",
                borderRadius: "8px",
                marginBottom: "2rem",
              }}
            >
              <h3 style={{ color: "#10b981", margin: "0 0 0.5rem" }}>✅ Aboneliğiniz Aktifleştirildi</h3>
              <p style={{ margin: "0 0 1rem", fontSize: "0.95rem" }}>
                Robot yönetim paneli yetkileriniz tanımlandı. Artık cihazlarınızı bağlayabilir, canlı telemetri ve LiDAR ortam krokisine erişebilirsiniz.
              </p>
              <div style={{ display: "flex", gap: "1rem" }}>
                <Link className="btn btn--primary" href="/panel">
                  Robot Paneline Geçin
                </Link>
                <Link className="btn btn--quiet" href="/panel/faturalar">
                  Fatura Geçmişi
                </Link>
              </div>
            </div>
          )}

          <dl className="kunye">
            <div>
              <dt>Sipariş numarası</dt>
              <dd className="mono">{siparis.id}</dd>
            </div>
            <div>
              <dt>Durum</dt>
              <dd>{DURUM_BASLIK[siparis.status] ?? siparis.status}</dd>
            </div>
            <div>
              <dt>Tutar</dt>
              <dd className="mono">{kurusBicimle(siparis.totalMinor)}</dd>
            </div>
          </dl>

          <ul className="liste" style={{ margin: "1.5rem 0" }}>
            {kalemler.map((k) => (
              <li key={k.id}>
                <strong>{k.name}</strong> × {k.quantity} — {kurusBicimle(k.unitPriceMinor * k.quantity)}
              </li>
            ))}
          </ul>

          {!basarili && (
            <p>
              <Link className="btn btn--primary" href="/fiyatlandirma">
                Yeniden Deneyin
              </Link>
            </p>
          )}
        </div>
      </section>
    </SayfaKabuk>
  );
}
