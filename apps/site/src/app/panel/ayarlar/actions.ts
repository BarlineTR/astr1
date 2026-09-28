"use server";

import { revalidatePath } from "next/cache";
import fs from "node:fs";
import path from "node:path";
import os from "node:os";
import { robotAyarlariGuncelle } from "@/db/sorgular/ayarlar";
import { oturumGerekli } from "@/lib/oturum";
import { kullanicininCihazlari } from "@/db/sorgular/cihaz";

export interface AyarlarSonuc {
  ok: boolean;
  hata?: string;
  mesaj?: string;
}

const MEMORY_FILE_PATHS = [
  path.resolve(process.cwd(), "../../ros2_ws/astro_memory.json"),
  "/home/okistech/Desktop/astr1/ros2_ws/astro_memory.json",
];

const SETTINGS_FILE_PATHS = [
  path.resolve(process.cwd(), "../../config/robot_settings.json"),
  path.join(os.homedir(), ".astro/active_settings.json"),
  "/home/okistech/Desktop/astr1/config/robot_settings.json",
];

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
  const ttsVoice = String(form.get("ttsVoice") ?? "echo");
  const persona = String(form.get("persona") ?? "kufurbaz");
  const llmPrompt = String(form.get("llmPrompt") ?? "");
  const greetingMessage = String(form.get("greetingMessage") ?? "");
  const alertOnUnknown = form.get("alertOnUnknown") === "on";
  const alertEmail = String(form.get("alertEmail") ?? "").trim() || null;

  try {
    await robotAyarlariGuncelle(cihazId, {
      persona,
      voiceSpeed,
      voicePitch,
      ttsVoice,
      llmPrompt,
      greetingMessage,
      alertOnUnknown,
      alertEmail,
    });

    const settingsObj = {
      persona,
      voiceSpeed,
      voicePitch,
      ttsVoice,
      llmPrompt,
      greetingMessage,
      alertOnUnknown,
      updatedAt: new Date().toISOString(),
    };

    // 1. Ayarları yerel yapılandırma dosyalarına yaz
    for (const p of SETTINGS_FILE_PATHS) {
      try {
        const dir = path.dirname(p);
        if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
        fs.writeFileSync(p, JSON.stringify(settingsObj, null, 2), "utf-8");
      } catch (e) {
        // yoksay
      }
    }

    // 2. astro_memory.json içindeki current_persona alanını güncelle
    for (const p of MEMORY_FILE_PATHS) {
      try {
        if (fs.existsSync(p)) {
          const raw = fs.readFileSync(p, "utf-8");
          const mem = JSON.parse(raw);
          mem.current_persona = persona;
          fs.writeFileSync(p, JSON.stringify(mem, null, 2), "utf-8");
        }
      } catch (e) {
        // yoksay
      }
    }

    revalidatePath("/panel/ayarlar");
    return { ok: true, mesaj: "Ayarlar başarıyla güncellendi ve robota canlı olarak uygulandı." };
  } catch (err) {
    console.error("Ayarlar güncelleme hatası:", err);
    return { ok: false, hata: "Ayarlar kaydedilemedi." };
  }
}
