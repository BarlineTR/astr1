import { notFound } from "next/navigation";

import { odemeSaglayici } from "@/lib/odeme";
import type { SahteAbonelikEk } from "@/lib/odeme/sahte-abonelik";
import { SahteOdemeFormu } from "@/components/SahteOdemeFormu";
import { SayfaKabuk } from "@/components/SayfaKabuk";
import { sayfaMetadata } from "@/lib/seo";

export const metadata = sayfaMetadata({
  baslik: "Abonelik ödemesi (taklit)",
  aciklama: "Geliştirme ortamı abonelik taklidi.",
  yol: "/odeme/sahte-abonelik",
  dizinleme: false,
});

export default async function SahteAbonelikSayfasi({
  params,
}: PageProps<"/odeme/sahte-abonelik/[token]">) {
  const { token } = await params;
  const saglayici = odemeSaglayici();
  if (saglayici.id !== "sahte") notFound();

  const ek = saglayici as unknown as SahteAbonelikEk;
  const ozet = ek.sahteAbonelikOzeti(token);
  if (!ozet) notFound();

  return (
    <SayfaKabuk
      current="fiyatlandirma"
      ustBaslik="Geliştirme ortamı"
      baslik="Abonelik ödemesi"
      lead="Kart bilgileriniz saklanır ve her dönem otomatik çekim yapılır. Bu ekran bir taklittir."
    >
      <section className="section">
        <div className="page">
          <p className="uyari-serit">
            Bu ekran bir <strong>taklittir</strong>. Gerçek bir kart girilmez, para
            hareket etmez ve girdiğiniz hiçbir bilgi sunucuya gönderilmez. Gerçek
            akışta kart iyzico tarafında saklanır ve tekrarlayan çekimi iyzico yürütür.
          </p>
          <SahteOdemeFormu
            token={token}
            tutarKurus={ozet.tutarKurus}
            kalemAdi={ozet.kalemAdi}
            periyot="ay"
            kararUcu="/api/odeme/sahte-abonelik-karar"
            geriDonusUcu="/api/odeme/abonelik-geri-donus"
          />
        </div>
      </section>
    </SayfaKabuk>
  );
}
