"use server";

import { randomUUID } from "node:crypto";

import { headers } from "next/headers";
import { z } from "zod";

import { db } from "@/db";
import { auditEvents, devices } from "@/db/schema";
import { tekilIhlalMi } from "@/db/hata";
import {
  ESLESTIRME_OMRU_MS,
  eslestirmeKoduUret,
  koduOzetle,
} from "@/lib/eslestirme";
import { oturumAl } from "@/lib/oturum";

export interface RobotEkleSonuc {
  ok: boolean;
  /** Yalnızca bu yanıtta döner ve bir daha gösterilemez. */
  kod?: string;
  cihazAdi?: string;
  hatalar?: Record<string, string>;
}

const girdiSchema = z.object({
  ad: z.string().trim().min(2, "Robota bir ad verin.").max(80),
  seri: z
    .string()
    .trim()
    .min(4, "Seri numarası en az 4 karakter.")
    .max(64)
    .regex(/^[A-Za-z0-9-]+$/, "Seri numarası yalnızca harf, rakam ve tire içerebilir."),
});

/**
 * Robot ekler ve tek kullanımlık eşleştirme kodu üretir.
 *
 * Kod yalnızca bu yanıtta döner; veritabanına özeti yazılır. Kullanıcı kodu
 * kaybederse yenisini üretir — kaybolan kodu geri getirmenin yolu yok ve
 * olmamalı da.
 */
export async function robotEkle(
  _onceki: RobotEkleSonuc | null,
  form: FormData,
): Promise<RobotEkleSonuc> {
  const oturum = await oturumAl();
  if (!oturum) return { ok: false, hatalar: { genel: "Oturum bulunamadı." } };

  const cozulmus = girdiSchema.safeParse({
    ad: form.get("ad"),
    seri: form.get("seri"),
  });

  if (!cozulmus.success) {
    const hatalar: Record<string, string> = {};
    for (const sorun of cozulmus.error.issues) {
      const alan = String(sorun.path[0] ?? "genel");
      hatalar[alan] ??= sorun.message;
    }
    return { ok: false, hatalar };
  }

  const { ad, seri } = cozulmus.data;
  const kod = eslestirmeKoduUret();
  const basliklar = await headers();
  const ip = basliklar.get("x-forwarded-for")?.split(",")[0]?.trim() ?? null;
  const cihazId = randomUUID();

  try {
    await db.insert(devices).values({
      id: cihazId,
      serial: seri.toUpperCase(),
      name: ad,
      ownerUserId: oturum.user.id,
      pairingCodeHash: koduOzetle(kod),
      pairingExpiresAt: new Date(Date.now() + ESLESTIRME_OMRU_MS),
      status: "eslestirme-bekliyor",
    });
  } catch (hata) {
    /*
     * Seri numarası tekil. Hata koduna bakılıyor, metne değil: Drizzle hatayı
     * sarıyor ve özgün mesaj cause zincirinde kalıyor — metin eşleştiren
     * kontrol ıskalıyor ve kullanıcı anlaşılır bir hata yerine 500 alıyordu.
     */
    if (tekilIhlalMi(hata, "devices_serial_unique")) {
      return { ok: false, hatalar: { seri: "Bu seri numarası zaten kayıtlı." } };
    }
    throw hata;
  }

  await db.insert(auditEvents).values({
    id: randomUUID(),
    actorUserId: oturum.user.id,
    deviceId: cihazId,
    kind: "cihaz.eklendi",
    // Kodun kendisi denetim kaydına da yazılmaz.
    payload: { serial: seri.toUpperCase(), name: ad },
    result: "ok",
    ipAddress: ip,
  });

  return { ok: true, kod, cihazAdi: ad };
}
