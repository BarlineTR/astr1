import { notFound } from "next/navigation";

import { odemeSaglayici } from "@/lib/odeme";
import type { SahteSaglayiciEk } from "@/lib/odeme/sahte";
import { SahteOdemeFormu } from "@/components/SahteOdemeFormu";
import { SayfaKabuk } from "@/components/SayfaKabuk";
import { sayfaMetadata } from "@/lib/seo";

export const metadata = sayfaMetadata({
  baslik: "Ödeme (taklit)",
  aciklama: "Geliştirme ortamı ödeme taklidi.",
  yol: "/odeme/sahte",
  dizinleme: false,
});

/**
 * Sahte sağlayıcının ödeme sayfası taklidi.
 *
 * Yalnızca iyzico anahtarları yokken var olur: gerçek sağlayıcı seçiliyse bu
 * adres 404 döner. Bütün sipariş yaşam döngüsünün anahtar olmadan da uçtan uca
 * koşabilmesi için, ve gerçekte bu adım iyzico'nun kendi sayfasında geçiyor.
 */
export default async function SahteOdemeSayfasi({
  params,
}: PageProps<"/odeme/sahte/[token]">) {
  const { token } = await params;
  const saglayici = odemeSaglayici();

  if (saglayici.id !== "sahte") notFound();

  const ek = saglayici as unknown as SahteSaglayiciEk;
  if (!ek.sahteOturumVarMi(token)) notFound();

  return (
    <SayfaKabuk
      current="fiyatlandirma"
      ustBaslik="Geliştirme ortamı"
      baslik="Ödeme taklidi"
      lead="Bu sayfa gerçek bir ödeme sayfası değil. iyzico anahtarları tanımlı olmadığı için sahte sağlayıcı kullanılıyor."
    >
      <section className="section">
        <div className="page">
          <p className="uyari-serit">
            Gerçek bir kart girilmez ve para hareket etmez. Gerçek akışta bu adım
            iyzico&apos;nun kendi sayfasında geçer ve kart bilgisi bizim sunucumuza
            hiç uğramaz.
          </p>
          <SahteOdemeFormu token={token} />
        </div>
      </section>
    </SayfaKabuk>
  );
}
