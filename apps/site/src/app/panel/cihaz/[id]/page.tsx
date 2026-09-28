import { notFound } from "next/navigation";

import { CihazYonetimi } from "@/components/CihazYonetimi";
import { Konsol } from "@/components/Konsol";
import { cihazErisimi, komutVerebilir } from "@/db/sorgular/cihaz";
import { PANEL_JETON_OMRU_MS, panelJetonuImzala } from "@/lib/cihaz-jeton";
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

  const baslangicJetonu = panelJetonuImzala({
    cihazId: erisim.cihaz.id,
    kullaniciId: oturum.user.id,
    komutVerebilir: komutVerebilir(erisim.yetki),
    exp: Date.now() + PANEL_JETON_OMRU_MS,
  });
  const gecitUrl = process.env.NEXT_PUBLIC_GECIT_URL ?? "ws://192.168.1.111:8420";

  return (
    <>
      <div className="pano__baslik pano__baslik--eylemli">
        <div>
          <h1>{cihaz.name}</h1>
          <p className="pano__lead cihaz-basligi__seri mono">{cihaz.serial}</p>
        </div>
        <span className="cihaz__durum">{DURUM_ADI[cihaz.status] ?? cihaz.status}</span>
      </div>

      <Konsol
        mod="canli"
        cihazId={cihaz.id}
        komutVerebilir={komutVerebilir(yetki)}
        baslangicJetonu={baslangicJetonu}
        gecitUrl={gecitUrl}
      />

      {/* Yönetim yalnızca sahibe görünür: operatör cihazı kullanır, bağlamaz. */}
      {yetki === "sahip" && (
        <CihazYonetimi cihazId={cihaz.id} seri={cihaz.serial} kodGecerliMi={kodGecerli} />
      )}
    </>
  );
}
