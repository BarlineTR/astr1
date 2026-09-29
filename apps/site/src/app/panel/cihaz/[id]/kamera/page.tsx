import Link from "next/link";
import { notFound } from "next/navigation";

import { cihazErisimi } from "@/db/sorgular/cihaz";
import { oturumGerekli } from "@/lib/oturum";
import { sayfaMetadata } from "@/lib/seo";
import { KameraGorunumu } from "@/components/KameraGorunumu";

export const metadata = sayfaMetadata({
  baslik: "Canlı Kamera",
  aciklama: "Robot kamera akışı — tam ekran.",
  yol: "/panel",
  dizinleme: false,
});

export default async function KameraSayfasi({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const oturum = await oturumGerekli(`/panel/cihaz/${id}/kamera`);

  const erisim = await cihazErisimi(id, oturum.user.id);
  if (!erisim) notFound();

  const { cihaz } = erisim;

  // Robot web ajanı her zaman 8080 portunda MJPEG yayını yapar.
  // Hostname dinamik alınır (client-side) çünkü SSR sırasında Jetson IP'si bilinmiyor olabilir.
  const streamUrl = process.env.NEXT_PUBLIC_ROBOT_STREAM_URL ?? null;

  return (
    <div className="kamera-sayfa">
      <div className="kamera-sayfa__ust">
        <Link href={`/panel/cihaz/${id}`} className="btn btn--sm">
          ← Konsola Dön
        </Link>
        <span className="kamera-sayfa__cihaz">{cihaz.name}</span>
        <span className="badge badge--live">
          <span className="badge__dot" />
          Canlı Yayın
        </span>
      </div>

      <KameraGorunumu cihazId={id} sabitStreamUrl={streamUrl} />
    </div>
  );
}
