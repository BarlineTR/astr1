import { NextResponse } from "next/server";
import { db } from "@/db";
import { devices, robotSettings, people, patrolWaypoints } from "@/db/schema";
import { eq } from "drizzle-orm";

export async function GET(request: Request) {
  try {
    const url = new URL(request.url);
    const serial = url.searchParams.get("serial") || "ASTRO-V1-000123";

    // 1. Cihazı bul
    const [cihaz] = await db
      .select()
      .from(devices)
      .where(eq(devices.serial, serial))
      .limit(1);

    if (!cihaz) {
      return NextResponse.json({ ok: false, hata: "Cihaz bulunamadı" }, { status: 404 });
    }

    // 2. Robot ayarlarını getir
    const [ayarlar] = await db
      .select()
      .from(robotSettings)
      .where(eq(robotSettings.deviceId, cihaz.id))
      .limit(1);

    // 3. Tanımlı kişileri getir
    const kisiler = cihaz.ownerUserId
      ? await db
          .select({
            id: people.id,
            name: people.name,
            role: people.role,
            notes: people.notes,
            hasPhoto: people.photoBase64,
          })
          .from(people)
          .where(eq(people.ownerUserId, cihaz.ownerUserId))
      : [];

    // 4. Devriye noktalarını getir
    const noktalar = await db
      .select()
      .from(patrolWaypoints)
      .where(eq(patrolWaypoints.deviceId, cihaz.id));

    return NextResponse.json({
      ok: true,
      cihaz: {
        id: cihaz.id,
        serial: cihaz.serial,
        name: cihaz.name,
      },
      ayarlar: ayarlar
        ? {
            persona: ayarlar.persona,
            ttsVoice: ayarlar.ttsVoice,
            voiceSpeed: ayarlar.voiceSpeed,
            voicePitch: ayarlar.voicePitch,
            llmPrompt: ayarlar.llmPrompt,
            greetingMessage: ayarlar.greetingMessage,
            alertOnUnknown: ayarlar.alertOnUnknown,
            patrolActive: ayarlar.patrolActive,
            speechOrientation: ayarlar.speechOrientation,
            quietMode: ayarlar.quietMode,
            sleepMode: ayarlar.sleepMode,
            proactiveGreeting: ayarlar.proactiveGreeting,
            updatedAt: ayarlar.updatedAt ? new Date(ayarlar.updatedAt).toISOString() : new Date().toISOString(),
          }
        : null,
      kisiler: kisiler.map((k) => ({
        id: k.id,
        name: k.name,
        role: k.role,
        notes: k.notes,
        hasPhoto: Boolean(k.hasPhoto),
      })),
      noktalar: noktalar.map((n) => ({
        id: n.id,
        name: n.name,
        x: n.x,
        y: n.y,
        yaw: n.yaw,
      })),
    });
  } catch (err: any) {
    console.error("API /api/cihaz/ayarlar hatası:", err);
    return NextResponse.json({ ok: false, hata: err?.message || "Sunucu hatası" }, { status: 500 });
  }
}
