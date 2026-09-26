import { randomUUID } from "node:crypto";

import { headers } from "next/headers";
import { NextResponse } from "next/server";
import { z } from "zod";

import { db } from "@/db";
import { consents } from "@/db/schema";
import { auth } from "@/lib/auth";

const govdeSchema = z.object({
  kind: z.enum(["kvkk", "cerez", "ticari-ileti"]),
  textVersion: z.string().min(1).max(64),
});

/**
 * Onay kaydı.
 *
 * Girişli ya da girişsiz çağrılabilir: iletişim formu da onay veriyor ve o
 * onayın da kaydı tutulmalı. Metin sürümü zorunlu — hangi metne onay verildiği
 * bilinmeden onay ispatlanamaz.
 */
export async function POST(istek: Request) {
  const cozulmus = govdeSchema.safeParse(await istek.json().catch(() => null));
  if (!cozulmus.success) {
    return NextResponse.json({ hata: "Geçersiz onay kaydı" }, { status: 400 });
  }

  const basliklar = await headers();
  const oturum = await auth.api.getSession({ headers: basliklar });

  await db.insert(consents).values({
    id: randomUUID(),
    userId: oturum?.user.id ?? null,
    kind: cozulmus.data.kind,
    textVersion: cozulmus.data.textVersion,
    // Ters vekil arkasında gerçek adres X-Forwarded-For'da olur.
    ipAddress: basliklar.get("x-forwarded-for")?.split(",")[0]?.trim() ?? null,
    userAgent: basliklar.get("user-agent") ?? null,
  });

  return NextResponse.json({ ok: true });
}
