import { and, eq, isNull, or } from "drizzle-orm";

import { db } from "@/db";
import { deviceGrants, devices } from "@/db/schema";

export type CihazYetkisi = "sahip" | "operator" | "viewer";

export interface CihazErisimi {
  cihaz: typeof devices.$inferSelect;
  yetki: CihazYetkisi;
}

/**
 * Kullanıcının bir cihaza erişimi.
 *
 * Erişim iki yoldan gelebilir: cihazın sahibi olmak ya da kendisine yetki
 * verilmiş olmak. İkisi de yoksa `null` döner ve çağıran taraf 404 verir —
 * 403 o kimlikte bir cihazın gerçekten var olduğunu söyler ve kimlikleri
 * tarayarak envanter çıkarmaya izin verir.
 *
 * İptal edilmiş cihazlar hiç dönmez.
 */
export async function cihazErisimi(
  cihazId: string,
  kullaniciId: string,
): Promise<CihazErisimi | null> {
  const [satir] = await db
    .select({ cihaz: devices, grant: deviceGrants })
    .from(devices)
    .leftJoin(
      deviceGrants,
      and(eq(deviceGrants.deviceId, devices.id), eq(deviceGrants.userId, kullaniciId)),
    )
    .where(
      and(
        eq(devices.id, cihazId),
        isNull(devices.revokedAt),
        or(eq(devices.ownerUserId, kullaniciId), eq(deviceGrants.userId, kullaniciId)),
      ),
    )
    .limit(1);

  if (!satir) return null;

  const yetki: CihazYetkisi =
    satir.cihaz.ownerUserId === kullaniciId ? "sahip" : (satir.grant?.role ?? "viewer");

  return { cihaz: satir.cihaz, yetki };
}

/** Komut gönderebilir mi. İzleyici yalnızca bakar. */
export function komutVerebilir(yetki: CihazYetkisi): boolean {
  return yetki === "sahip" || yetki === "operator";
}

/** Kullanıcının cihazları. İptal edilmişler listelenmez. */
export async function kullanicininCihazlari(kullaniciId: string) {
  return db
    .select()
    .from(devices)
    .where(and(eq(devices.ownerUserId, kullaniciId), isNull(devices.revokedAt)));
}
