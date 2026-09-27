"use server";

import { revalidatePath } from "next/cache";
import { robotAyarlariGuncelle } from "@/db/sorgular/ayarlar";
import { oturumGerekli } from "@/lib/oturum";
import { kullanicininCihazlari } from "@/db/sorgular/cihaz";

export interface AyarlarSonuc {
  ok: boolean;
  hata?: string;
  mesaj?: string;
}

export async function ayarlarKaydet(
  _onceki: AyarlarSonuc | null,
  form: FormData,
): Promise<AyarlarSonuc> {
  const oturum = await oturumGerekli("/panel/ayarlar");
  const cihazId = String(form.get("deviceId") ?? "");

  const cihazlar = await kullanicininCihazlari(oturum.user.id);
  const yetkili = cihazlar.some((c) => c.id === cihazId);
  if (!yetkili) {
    return { ok: false, hata: "Bu cihaz üzerinde yetkiniz yok." };
  }

  const voiceSpeed = Number(form.get("voiceSpeed") ?? 100);
  const voicePitch = Number(form.get("voicePitch") ?? 100);
  const ttsVoice = String(form.get("ttsVoice") ?? "tr_tr_male");
  const llmPrompt = String(form.get("llmPrompt") ?? "");
  const greetingMessage = String(form.get("greetingMessage") ?? "");
  const alertOnUnknown = form.get("alertOnUnknown") === "on";
  const alertEmail = String(form.get("alertEmail") ?? "").trim() || null;

  try {
    await robotAyarlariGuncelle(cihazId, {
      voiceSpeed,
      voicePitch,
      ttsVoice,
      llmPrompt,
      greetingMessage,
      alertOnUnknown,
      alertEmail,
    });
    revalidatePath("/panel/ayarlar");
    return { ok: true, mesaj: "Ayarlar başarıyla güncellendi ve robota iletildi." };
  } catch (err) {
    console.error("Ayarlar güncelleme hatası:", err);
    return { ok: false, hata: "Ayarlar kaydedilemedi." };
  }
}
