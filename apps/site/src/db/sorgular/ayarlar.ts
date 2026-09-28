import { randomUUID } from "node:crypto";
import { eq } from "drizzle-orm";

import { db } from "@/db";
import { robotSettings } from "@/db/schema";

export async function robotAyarlariGetir(deviceId: string) {
  const [kayit] = await db
    .select()
    .from(robotSettings)
    .where(eq(robotSettings.deviceId, deviceId))
    .limit(1);

  if (kayit) return kayit;

  // Varsayılan ayarları oluştur
  const id = randomUUID();
  const [varsayilan] = await db
    .insert(robotSettings)
    .values({
      id,
      deviceId,
      voiceSpeed: 100,
      voicePitch: 100,
      ttsVoice: "echo",
      persona: "kufurbaz",
      llmPrompt: "Sen Astro'sun! Aşırı zeki, sivri dilli, acımasız sokak mizahı ve dobra sokak dili kullanan, lafı gediğine koyan bir robotsun.",
      greetingMessage: "Selam, ne var ne yok?",
      alertOnUnknown: true,
      patrolActive: false,
      speechOrientation: "autonomous",
      quietMode: false,
      sleepMode: false,
      proactiveGreeting: true,
    })
    .returning();

  if (!varsayilan) {
    throw new Error("Varsayılan ayarlar oluşturulamadı");
  }

  return varsayilan;
}

export async function robotAyarlariGuncelle(
  deviceId: string,
  girdi: {
    persona?: string;
    voiceSpeed?: number;
    voicePitch?: number;
    ttsVoice?: string;
    llmPrompt?: string;
    greetingMessage?: string;
    alertOnUnknown?: boolean;
    alertEmail?: string | null;
    patrolActive?: boolean;
    speechOrientation?: string;
    quietMode?: boolean;
    sleepMode?: boolean;
    proactiveGreeting?: boolean;
  },
) {
  await db
    .update(robotSettings)
    .set({
      ...girdi,
      updatedAt: new Date(),
    })
    .where(eq(robotSettings.deviceId, deviceId));
}

