"use server";

import { revalidatePath } from "next/cache";
import fs from "node:fs";
import path from "node:path";
import { noktaEkle, noktaSil, cihazinNoktalari } from "@/db/sorgular/harita";
import { oturumGerekli } from "@/lib/oturum";
import { kullanicininCihazlari } from "@/db/sorgular/cihaz";

const WAYPOINTS_JSON_PATHS = [
  path.resolve(process.cwd(), "../../config/waypoints_office.json"),
  "/home/okistech/Desktop/astr1/config/waypoints_office.json",
];

async function syncWaypointsToFile(deviceId: string) {
  try {
    const noktalar = await cihazinNoktalari(deviceId);
    const waypointsObj: Record<string, any> = {};

    for (const n of noktalar) {
      const key = n.name.toLowerCase().replace(/[^a-z0-9]/g, "_");
      waypointsObj[key] = {
        name: n.name,
        aliases: [n.name.toLowerCase()],
        x: Number(n.x),
        y: Number(n.y),
        yaw_deg: Number(n.yaw || 0),
        description: `Panel üzerinden tanımlanan ${n.name} devriye noktası.`,
        arrival_message: `${n.name} noktasına ulaştık.`,
      };
    }

    const payload = {
      mode: "office",
      description: "ASTRO Ofis Karşılama ve Rehberlik Noktaları (Web Panel Eşitlemeli)",
      default_home: "reception",
      waypoints: waypointsObj,
    };

    for (const p of WAYPOINTS_JSON_PATHS) {
      if (fs.existsSync(p) || fs.existsSync(path.dirname(p))) {
        fs.writeFileSync(p, JSON.stringify(payload, null, 2), "utf-8");
      }
    }
  } catch (err) {
    console.error("waypoints_office.json senkronizasyon hatası:", err);
  }
}

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
  await syncWaypointsToFile(deviceId);
  revalidatePath("/panel/harita");
}

export async function waypointSil(id: string, deviceId: string) {
  const oturum = await oturumGerekli("/panel/harita");
  const cihazlar = await kullanicininCihazlari(oturum.user.id);
  if (!cihazlar.some((c) => c.id === deviceId)) {
    throw new Error("Yetkisiz işlem");
  }

  await noktaSil(id, deviceId);
  await syncWaypointsToFile(deviceId);
  revalidatePath("/panel/harita");
}
