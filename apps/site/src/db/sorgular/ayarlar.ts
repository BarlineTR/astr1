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
      ttsVoice: "tr_tr_male",
      llmPrompt: "Sen yardımsever, kibar ve cana yakın bir sosyal robotsun. Kısa ve öz konuşursun.",
      greetingMessage: "Merhaba, size nasıl yardımcı olabilirim?",
      alertOnUnknown: true,
      patrolActive: false,
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
    voiceSpeed?: number;
    voicePitch?: number;
    ttsVoice?: string;
    llmPrompt?: string;
    greetingMessage?: string;
    alertOnUnknown?: boolean;
    alertEmail?: string | null;
    patrolActive?: boolean;
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
