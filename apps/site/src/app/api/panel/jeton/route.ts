import { NextResponse } from "next/server";
import { z } from "zod";

import { cihazErisimi, komutVerebilir } from "@/db/sorgular/cihaz";
import {
  PANEL_JETON_OMRU_MS,
  panelJetonuImzala,
} from "@/lib/cihaz-jeton";
import { oturumAl } from "@/lib/oturum";

const govdeSchema = z.object({ cihazId: z.string().min(1).max(64) });

/**
 * Konsol için kısa ömürlü ağ geçidi jetonu.
 *
 * Tarayıcı ağ geçidine doğrudan bağlanıyor ama yetkiyi site veriyor: erişim
 * kontrolü veritabanını gören tarafta kalmalı. Jeton 60 saniyelik ve yalnızca
 * bağlantı kurulumu için — kurulan bağlantı jeton dolunca kopmuyor.
 */
export async function POST(istek: Request) {
  const oturum = await oturumAl();
  if (!oturum) return NextResponse.json({ ok: false }, { status: 401 });

  const cozulmus = govdeSchema.safeParse(await istek.json().catch(() => null));
  if (!cozulmus.success) return NextResponse.json({ ok: false }, { status: 400 });

  const erisim = await cihazErisimi(cozulmus.data.cihazId, oturum.user.id);
  // 403 değil 404: 403 o kimlikte bir cihazın var olduğunu söyler.
  if (!erisim) return NextResponse.json({ ok: false }, { status: 404 });

  const token = panelJetonuImzala({
    cihazId: erisim.cihaz.id,
    kullaniciId: oturum.user.id,
    komutVerebilir: komutVerebilir(erisim.yetki),
    exp: Date.now() + PANEL_JETON_OMRU_MS,
  });

  return NextResponse.json({
    ok: true,
    token,
    gecitUrl: process.env.NEXT_PUBLIC_GECIT_URL ?? "ws://localhost:8420",
  });
}
