import { oturumGerekli } from "@/lib/oturum";
import { sayfaMetadata } from "@/lib/seo";

export const metadata = sayfaMetadata({
  baslik: "Hesap",
  aciklama: "Hesap bilgileriniz.",
  yol: "/panel/hesap",
  dizinleme: false,
});

const ROL_ADI: Record<string, string> = {
  customer: "Müşteri",
  operator: "Operatör",
  admin: "Yönetici",
};

export default async function HesapSayfasi() {
  const { user } = await oturumGerekli("/panel/hesap");

  return (
    <>
      <div className="panel__baslik">
        <h1>Hesap</h1>
        <p className="panel__lead">Hesap bilgileriniz ve yetki seviyeniz.</p>
      </div>

      <dl className="kunye">
        <div>
          <dt>Ad soyad</dt>
          <dd>{user.name}</dd>
        </div>
        <div>
          <dt>E-posta</dt>
          <dd>
            {user.email}
            {!user.emailVerified && (
              <span className="rozet rozet--uyari"> doğrulanmadı</span>
            )}
          </dd>
        </div>
        <div>
          <dt>Yetki</dt>
          <dd>{ROL_ADI[(user as { role?: string }).role ?? "customer"] ?? "Müşteri"}</dd>
        </div>
      </dl>
    </>
  );
}
