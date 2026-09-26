import { KURUM } from "@/data/kurum";
import { oturumGerekli } from "@/lib/oturum";
import { sayfaMetadata } from "@/lib/seo";

export const metadata = sayfaMetadata({
  baslik: "Faturalar",
  aciklama: "Ödeme geçmişiniz ve faturalarınız.",
  yol: "/panel",
  dizinleme: false,
});

export default async function FaturalarSayfasi() {
  const oturum = await oturumGerekli("/panel/faturalar");

  /*
   * Fatura kaydı ödemeyle birlikte oluşur; ödeme sağlayıcısı bağlanmadan
   * fatura da yok. Sahte bir liste göstermektense boş durum anlatıyor.
   */
  const faturalar: ReadonlyArray<{ id: string }> = [];

  return (
    <>
      <div className="pano__baslik">
        <h1>Faturalar</h1>
        <p className="pano__lead">Ödeme geçmişiniz ve indirilebilir faturalarınız.</p>
      </div>

      {faturalar.length === 0 && (
        <div className="bos-durum">
          <p className="eyebrow">Henüz fatura yok</p>
          <p>
            İlk ödemeniz gerçekleştiğinde faturalarınız burada listelenir ve PDF
            olarak indirilebilir.
          </p>
          <p className="bos-durum__not">
            Faturalar <strong>{oturum.user.email}</strong> adresine de gönderilir.
          </p>
        </div>
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
          <a href={`mailto:${KURUM.eposta}`}>bize iletin</a>; fatura alanları ödeme
          altyapısıyla birlikte düzenlenebilir hale gelecek.
        </p>
      </section>
    </>
  );
}
