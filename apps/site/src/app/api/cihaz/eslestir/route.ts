import { randomUUID } from "node:crypto";

import { and, eq, isNull } from "drizzle-orm";
import { NextResponse } from "next/server";

import { PROTOCOL_VERSION } from "@astro/protocol";
import { eslestirmeIstegiSchema } from "@astro/protocol/wire";

import { db } from "@/db";
import { auditEvents, devices } from "@/db/schema";
import { cihazJetonuOzetle, cihazJetonuUret } from "@/lib/cihaz-jeton";
import { koduOzetle } from "@/lib/eslestirme";

/**
 * Eşleştirme: robot ajanı kodu uzun ömürlü jetonla değiştirir.
 *
 * Ağ geçidine değil siteye geliyor, çünkü cihaz kayıtları burada. Ağ geçidi
 * bilerek durumsuz bir röle.
 *
 * Hata mesajları ayrıntı vermiyor: "kod yanlış" ile "seri numarası yanlış"
 * arasındaki farkı söylemek, kod tahmin eden birine hangi adımda olduğunu
 * bildirmek demek.
 */
export async function POST(istek: Request) {
  const cozulmus = eslestirmeIstegiSchema.safeParse(
    await istek.json().catch(() => null),
  );
  if (!cozulmus.success) {
    return NextResponse.json({ ok: false, hata: "Geçersiz istek" }, { status: 400 });
  }

  const { kod, serial, firmware } = cozulmus.data;

  const [cihaz] = await db
    .select()
    .from(devices)
    .where(and(eq(devices.serial, serial.toUpperCase()), isNull(devices.revokedAt)))
    .limit(1);

  const kodOzeti = koduOzetle(kod);
  const gecerli =
    cihaz &&
    cihaz.pairingCodeHash === kodOzeti &&
    cihaz.pairingExpiresAt !== null &&
    cihaz.pairingExpiresAt > new Date();

  if (!cihaz || !gecerli) {
    if (cihaz) {
      await db.insert(auditEvents).values({
        id: randomUUID(),
        deviceId: cihaz.id,
        kind: "cihaz.eslestirme",
        result: "reddedildi",
        payload: { serial: serial.toUpperCase() },
      });
    }
    return NextResponse.json(
      { ok: false, hata: "Eşleştirme kodu geçersiz ya da süresi geçmiş." },
      { status: 401 },
    );
  }

  const jeton = cihazJetonuUret();

  await db
    .update(devices)
    .set({
      tokenHash: cihazJetonuOzetle(jeton),
      // Kod tek kullanımlık: eşleştirme tamamlandı, kod yakılıyor.
      pairingCodeHash: null,
      pairingExpiresAt: null,
      firmwareVersion: firmware ?? null,
      status: "cevrimdisi",
      lastSeenAt: new Date(),
    })
    .where(eq(devices.id, cihaz.id));

  await db.insert(auditEvents).values({
    id: randomUUID(),
    deviceId: cihaz.id,
    kind: "cihaz.eslestirildi",
    result: "ok",
    payload: { serial: cihaz.serial, firmware: firmware ?? null },
  });

  return NextResponse.json({
    ok: true,
    cihazId: cihaz.id,
    token: jeton,
    // Ajan adresi gömmez, site söyler: ağ geçidi taşınırsa ajan değişmez.
    gecitUrl: process.env.NEXT_PUBLIC_GECIT_URL ?? "ws://localhost:8420",
    v: PROTOCOL_VERSION,
  });
}
