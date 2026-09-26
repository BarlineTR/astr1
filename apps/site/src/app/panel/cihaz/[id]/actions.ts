"use server";

import { randomUUID } from "node:crypto";

import { eq } from "drizzle-orm";
import { revalidatePath } from "next/cache";
import { headers } from "next/headers";
import { redirect } from "next/navigation";

import { db } from "@/db";
import { auditEvents, devices } from "@/db/schema";
import { cihazErisimi } from "@/db/sorgular/cihaz";
import {
  ESLESTIRME_OMRU_MS,
  eslestirmeKoduUret,
  koduOzetle,
} from "@/lib/eslestirme";
import { oturumAl } from "@/lib/oturum";

export interface CihazIslemSonuc {
  ok: boolean;
  kod?: string;
  hata?: string;
}

async function denetimYaz(girdi: {
  kullaniciId: string;
  cihazId: string;
  kind: string;
  result: string;
  payload?: Record<string, unknown>;
}) {
  const basliklar = await headers();
  await db.insert(auditEvents).values({
    id: randomUUID(),
    actorUserId: girdi.kullaniciId,
    deviceId: girdi.cihazId,
    kind: girdi.kind,
    payload: girdi.payload ?? null,
    result: girdi.result,
    ipAddress: basliklar.get("x-forwarded-for")?.split(",")[0]?.trim() ?? null,
  });
}

/**
 * Eşleştirme kodunu yeniler.
 *
 * Kaybolan kodu geri getirmenin yolu yok — veritabanında yalnızca özeti duruyor
 * — ve olmamalı da. Yenisini üretmek eskisini geçersiz kılar.
 */
export async function koduYenile(
  _onceki: CihazIslemSonuc | null,
  form: FormData,
): Promise<CihazIslemSonuc> {
  const oturum = await oturumAl();
  if (!oturum) return { ok: false, hata: "Oturum bulunamadı." };

  const cihazId = String(form.get("cihazId") ?? "");
  const erisim = await cihazErisimi(cihazId, oturum.user.id);
  // Yalnızca sahip kod üretebilir: operatör cihazı kullanır, bağlamaz.
  if (!erisim || erisim.yetki !== "sahip") {
    return { ok: false, hata: "Bu işlem için yetkiniz yok." };
  }

  const kod = eslestirmeKoduUret();
  await db
    .update(devices)
    .set({
      pairingCodeHash: koduOzetle(kod),
      pairingExpiresAt: new Date(Date.now() + ESLESTIRME_OMRU_MS),
      /*
       * Eski jeton da iptal ediliyor: kod yenilemek "bu cihazı yeniden bağla"
       * demek ve eski ajanın bağlı kalması bunu anlamsız kılardı.
       */
      tokenHash: null,
      status: "eslestirme-bekliyor",
    })
    .where(eq(devices.id, cihazId));

  await denetimYaz({
    kullaniciId: oturum.user.id,
    cihazId,
    kind: "cihaz.kod-yenilendi",
    result: "ok",
  });

  revalidatePath(`/panel/cihaz/${cihazId}`);
  return { ok: true, kod };
}

/**
 * Cihazı siler.
 *
 * Satır silinmiyor, `revokedAt` doluyor: denetim kayıtları cihaza referans
 * veriyor ve silinen cihazın geçmişi de silinirse denetim kaydının anlamı
 * kalmaz. İptal edilmiş cihaz listelerde ve erişim kontrolünde hiç görünmez.
 *
 * Onay olarak seri numarası isteniyor: tek tıkla silinen bir cihaz, yanlışlıkla
 * silinen bir cihazdır.
 */
export async function cihaziSil(
  _onceki: CihazIslemSonuc | null,
  form: FormData,
): Promise<CihazIslemSonuc> {
  const oturum = await oturumAl();
  if (!oturum) return { ok: false, hata: "Oturum bulunamadı." };

  const cihazId = String(form.get("cihazId") ?? "");
  const onay = String(form.get("onay") ?? "").trim();

  const erisim = await cihazErisimi(cihazId, oturum.user.id);
  if (!erisim || erisim.yetki !== "sahip") {
    return { ok: false, hata: "Bu işlem için yetkiniz yok." };
  }

  if (onay.toUpperCase() !== erisim.cihaz.serial.toUpperCase()) {
    await denetimYaz({
      kullaniciId: oturum.user.id,
      cihazId,
      kind: "cihaz.sil",
      result: "onay-uyusmadi",
    });
    return { ok: false, hata: "Seri numarası eşleşmiyor." };
  }

  await db
    .update(devices)
    .set({
      revokedAt: new Date(),
      tokenHash: null,
      pairingCodeHash: null,
      pairingExpiresAt: null,
      status: "silindi",
    })
    .where(eq(devices.id, cihazId));

  await denetimYaz({
    kullaniciId: oturum.user.id,
    cihazId,
    kind: "cihaz.silindi",
    result: "ok",
    payload: { serial: erisim.cihaz.serial },
  });

  // redirect() NEXT_REDIRECT fırlatır; dönüş değeri buraya ulaşmaz.
  redirect("/panel");
}
