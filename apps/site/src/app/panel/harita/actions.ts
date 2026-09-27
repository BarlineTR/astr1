"use server";

import { revalidatePath } from "next/cache";
import { noktaEkle, noktaSil } from "@/db/sorgular/harita";
import { oturumGerekli } from "@/lib/oturum";
import { kullanicininCihazlari } from "@/db/sorgular/cihaz";

export async function waypointEkle(form: FormData) {
  const oturum = await oturumGerekli("/panel/harita");
  const deviceId = String(form.get("deviceId") ?? "");
  const name = String(form.get("name") ?? "").trim();
  const x = Number(form.get("x") ?? 0);
  const y = Number(form.get("y") ?? 0);

  const cihazlar = await kullanicininCihazlari(oturum.user.id);
  if (!cihazlar.some((c) => c.id === deviceId)) {
    throw new Error("Yetkisiz işlem");
  }

  if (name.length < 1) return;

  await noktaEkle(deviceId, name, x, y);
  revalidatePath("/panel/harita");
}

export async function waypointSil(id: string, deviceId: string) {
  const oturum = await oturumGerekli("/panel/harita");
  const cihazlar = await kullanicininCihazlari(oturum.user.id);
  if (!cihazlar.some((c) => c.id === deviceId)) {
    throw new Error("Yetkisiz işlem");
  }

  await noktaSil(id, deviceId);
  revalidatePath("/panel/harita");
}
