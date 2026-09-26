import { and, eq } from "drizzle-orm";
import { notFound } from "next/navigation";

import { db } from "@/db";
import { deviceGrants, devices } from "@/db/schema";
import { Konsol } from "@/components/Konsol";
import { oturumGerekli } from "@/lib/oturum";
import { sayfaMetadata } from "@/lib/seo";

export const metadata = sayfaMetadata({
  baslik: "Cihaz",
  aciklama: "Cihaz kontrol konsolu.",
  yol: "/panel",
  dizinleme: false,
});

export default async function CihazSayfasi({ params }: PageProps<"/panel/cihaz/[id]">) {
  const { id } = await params;
  const oturum = await oturumGerekli(`/panel/cihaz/${id}`);

  /*
   * Erişim iki yoldan gelebilir: cihazın sahibi olmak ya da kendisine yetki
   * verilmiş olmak. İkisi de yoksa 404 dönülür, 403 değil — 403 o kimlikte bir
   * cihazın gerçekten var olduğunu söyler ve kimlikleri tarayarak envanter
   * çıkarmaya izin verir.
   */
  const [cihaz] = await db
    .select()
    .from(devices)
    .where(and(eq(devices.id, id), eq(devices.ownerUserId, oturum.user.id)))
    .limit(1);

  const [yetki] = cihaz
    ? [null]
    : await db
        .select()
        .from(deviceGrants)
        .where(and(eq(deviceGrants.deviceId, id), eq(deviceGrants.userId, oturum.user.id)))
        .limit(1);

  if (!cihaz && !yetki) notFound();

  return (
    <>
      <div className="pano__baslik">
        <h1>{cihaz?.name ?? "Cihaz"}</h1>
        <p className="pano__lead mono">{cihaz?.serial ?? id}</p>
      </div>

      <Konsol mod="canli" />
    </>
  );
}
