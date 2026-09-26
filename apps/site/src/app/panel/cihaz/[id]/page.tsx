import { notFound } from "next/navigation";

import { CihazYonetimi } from "@/components/CihazYonetimi";
import { Konsol } from "@/components/Konsol";
import { cihazErisimi, komutVerebilir } from "@/db/sorgular/cihaz";
import { oturumGerekli } from "@/lib/oturum";
import { sayfaMetadata } from "@/lib/seo";

export const metadata = sayfaMetadata({
  baslik: "Cihaz",
  aciklama: "Cihaz kontrol konsolu.",
  yol: "/panel",
  dizinleme: false,
});

const DURUM_ADI: Record<string, string> = {
  kayitli: "kayıtlı",
  "eslestirme-bekliyor": "eşleştirme bekliyor",
  cevrimdisi: "çevrimdışı",
  cevrimici: "çevrimiçi",
};

export default async function CihazSayfasi({ params }: PageProps<"/panel/cihaz/[id]">) {
  const { id } = await params;
  const oturum = await oturumGerekli(`/panel/cihaz/${id}`);

  const erisim = await cihazErisimi(id, oturum.user.id);
  // 403 değil 404: 403 o kimlikte bir cihazın var olduğunu söyler.
  if (!erisim) notFound();

  const { cihaz, yetki } = erisim;
  const kodGecerli = Boolean(
    cihaz.pairingCodeHash && cihaz.pairingExpiresAt && cihaz.pairingExpiresAt > new Date(),
  );

  return (
    <>
      <div className="pano__baslik pano__baslik--eylemli">
        <div>
          <h1>{cihaz.name}</h1>
          <p className="pano__lead cihaz-basligi__seri mono">{cihaz.serial}</p>
        </div>
        <span className="cihaz__durum">{DURUM_ADI[cihaz.status] ?? cihaz.status}</span>
      </div>

      <Konsol mod="canli" cihazId={cihaz.id} komutVerebilir={komutVerebilir(yetki)} />

      {/* Yönetim yalnızca sahibe görünür: operatör cihazı kullanır, bağlamaz. */}
      {yetki === "sahip" && (
        <CihazYonetimi cihazId={cihaz.id} seri={cihaz.serial} kodGecerliMi={kodGecerli} />
      )}
    </>
  );
}
