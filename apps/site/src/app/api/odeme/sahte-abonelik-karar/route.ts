import { NextResponse } from "next/server";
import { z } from "zod";

import { odemeSaglayici } from "@/lib/odeme";
import type { SahteAbonelikEk } from "@/lib/odeme/sahte-abonelik";

const govdeSchema = z.object({
  token: z.string().min(8).max(200),
  sonuc: z.enum(["basarili", "basarisiz"]),
});

/** Taklit abonelik kararı. Gerçek sağlayıcıda bu uç 404 döner. */
export async function POST(istek: Request) {
  const saglayici = odemeSaglayici();
  if (saglayici.id !== "sahte") {
    return NextResponse.json({ ok: false }, { status: 404 });
  }

  const cozulmus = govdeSchema.safeParse(await istek.json().catch(() => null));
  if (!cozulmus.success) return NextResponse.json({ ok: false }, { status: 400 });

  const ek = saglayici as unknown as SahteAbonelikEk;
  const oldu = ek.sahteAbonelikKarar(cozulmus.data.token, cozulmus.data.sonuc);
  return NextResponse.json({ ok: oldu }, { status: oldu ? 200 : 404 });
}
