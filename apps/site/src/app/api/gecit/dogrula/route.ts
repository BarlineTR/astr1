import { timingSafeEqual } from "node:crypto";

import { and, eq, isNull } from "drizzle-orm";
import { NextResponse } from "next/server";
import { z } from "zod";

import { db } from "@/db";
import { devices } from "@/db/schema";
import { cihazJetonuOzetle, panelJetonuCoz } from "@/lib/cihaz-jeton";

/**
 * Ağ geçidinin jeton doğrulama ucu — **sunucudan sunucuya**.
 *
 * Ağ geçidi cihaz kayıtlarını tutmuyor; bağlantı kurulurken bir kez buraya
 * soruyor. Böylece iptal edilen bir cihaz bir sonraki bağlantıda giremiyor ve
 * ağ geçidi durumsuz kalıyor.
 */

const govdeSchema = z.object({
  tur: z.enum(["cihaz", "panel"]),
  token: z.string().min(8).max(2048),
});

function sirUyuyor(gelen: string | null): boolean {
  const beklenen = process.env.GATEWAY_SHARED_SECRET;
  // Sır tanımlı değilse uç tamamen kapalı: açık bırakmak doğrulamayı herkese
  // açmak olurdu.
  if (!beklenen || !gelen) return false;

  const a = Buffer.from(gelen);
  const b = Buffer.from(beklenen);
  return a.length === b.length && timingSafeEqual(a, b);
}

export async function POST(istek: Request) {
  if (!sirUyuyor(istek.headers.get("x-gecit-sirri"))) {
    return NextResponse.json({ ok: false }, { status: 401 });
  }

  const cozulmus = govdeSchema.safeParse(await istek.json().catch(() => null));
  if (!cozulmus.success) {
    return NextResponse.json({ ok: false }, { status: 400 });
  }

  const { tur, token } = cozulmus.data;

  if (tur === "cihaz") {
    const [cihaz] = await db
      .select()
      .from(devices)
      .where(
        and(eq(devices.tokenHash, cihazJetonuOzetle(token)), isNull(devices.revokedAt)),
      )
      .limit(1);

    if (!cihaz) return NextResponse.json({ ok: false }, { status: 200 });

    await db
      .update(devices)
      .set({ lastSeenAt: new Date(), status: "cevrimici" })
      .where(eq(devices.id, cihaz.id));

    return NextResponse.json({ ok: true, cihazId: cihaz.id, serial: cihaz.serial });
  }

  const icerik = panelJetonuCoz(token);
  if (!icerik) return NextResponse.json({ ok: false }, { status: 200 });

  /*
   * Jeton imzalı ama cihaz o sırada silinmiş olabilir: imza geçmişi değil o anı
   * doğrulamalı.
   */
  const [cihaz] = await db
    .select({ id: devices.id })
    .from(devices)
    .where(and(eq(devices.id, icerik.cihazId), isNull(devices.revokedAt)))
    .limit(1);

  if (!cihaz) return NextResponse.json({ ok: false }, { status: 200 });

  return NextResponse.json({
    ok: true,
    cihazId: icerik.cihazId,
    kullaniciId: icerik.kullaniciId,
    komutVerebilir: icerik.komutVerebilir,
  });
}
