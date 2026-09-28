"use server";

import { revalidatePath } from "next/cache";
import fs from "node:fs";
import path from "node:path";
import { kisiEkle, kisiSil } from "@/db/sorgular/kisiler";
import { oturumGerekli } from "@/lib/oturum";
import { db } from "@/db";
import { people } from "@/db/schema";
import { and, eq } from "drizzle-orm";
import type { KisiRol } from "@/db/schema";

export interface KisiKaydetSonuc {
  ok: boolean;
  hata?: string;
}

const KNOWN_FACES_DIRS = [
  path.resolve(process.cwd(), "../../ros2_ws/src/astro_vision/data/known_faces"),
  "/home/okistech/Desktop/astr1/ros2_ws/src/astro_vision/data/known_faces",
];

const MEMORY_FILE_PATHS = [
  path.resolve(process.cwd(), "../../ros2_ws/astro_memory.json"),
  "/home/okistech/Desktop/astr1/ros2_ws/astro_memory.json",
];

function sanitizeName(name: string): string {
  return name.toLowerCase().replace(/[^a-z0-9]/g, "_");
}

export async function kisiKaydet(
  _onceki: KisiKaydetSonuc | null,
  form: FormData,
): Promise<KisiKaydetSonuc> {
  const oturum = await oturumGerekli("/panel/kisiler");
  const ad = String(form.get("name") ?? "").trim();
  const rol = String(form.get("role") ?? "guest") as KisiRol;
  const notlar = String(form.get("notes") ?? "").trim();
  const photoBase64 = String(form.get("photoBase64") ?? "").trim() || null;

  if (ad.length < 2) {
    return { ok: false, hata: "Lütfen geçerli bir isim yazın (en az 2 karakter)." };
  }

  try {
    await kisiEkle({
      ownerUserId: oturum.user.id,
      name: ad,
      role: rol,
      notes: notlar,
      photoBase64,
    });

    // 1. Robot yüz klasörüne fotoğrafı yaz
    if (photoBase64) {
      try {
        const base64Data = photoBase64.replace(/^data:image\/\w+;base64,/, "");
        const buffer = Buffer.from(base64Data, "base64");
        const fileName = `${sanitizeName(ad)}.jpg`;

        for (const dir of KNOWN_FACES_DIRS) {
          if (fs.existsSync(dir)) {
            fs.writeFileSync(path.join(dir, fileName), buffer);
          }
        }
      } catch (err) {
        console.error("Yüz dosyası diske yazılamadı:", err);
      }
    }

    // 2. Robot astro_memory.json hafıza profiline ekle
    try {
      const cleanKey = sanitizeName(ad);
      for (const memPath of MEMORY_FILE_PATHS) {
        if (fs.existsSync(memPath)) {
          const raw = fs.readFileSync(memPath, "utf-8");
          const mem = JSON.parse(raw);
          if (!mem.known_people) mem.known_people = {};
          mem.known_people[cleanKey] = {
            name: ad,
            title: rol === "vip" ? "VIP Ziyaretçi" : (rol === "staff" ? "Personel" : "Kayıtlı Misafir"),
            formal_title: `${ad} Bey/Hanım`,
            notes: notlar,
            learned_facts: [],
            preferences: {},
            session_summaries: mem.known_people[cleanKey]?.session_summaries || [],
            learned_at: Date.now() / 1000,
          };
          fs.writeFileSync(memPath, JSON.stringify(mem, null, 2), "utf-8");
        }
      }
    } catch (err) {
      console.error("astro_memory.json güncellenemedi:", err);
    }

    revalidatePath("/panel/kisiler");
    return { ok: true };
  } catch (err) {
    console.error("Kişi ekleme hatası:", err);
    return { ok: false, hata: "Kişi kaydedilemedi. Lütfen tekrar deneyin." };
  }
}

export async function kisiKaldir(id: string) {
  const oturum = await oturumGerekli("/panel/kisiler");

  try {
    // Kişiyi silmeden önce adını al
    const [hedef] = await db
      .select({ name: people.name })
      .from(people)
      .where(and(eq(people.id, id), eq(people.ownerUserId, oturum.user.id)))
      .limit(1);

    await kisiSil(id, oturum.user.id);

    if (hedef?.name) {
      const cleanKey = sanitizeName(hedef.name);

      // 1. Dosya ve klasörleri sil
      for (const dir of KNOWN_FACES_DIRS) {
        try {
          const personDir = path.join(dir, cleanKey);
          if (fs.existsSync(personDir)) {
            fs.rmSync(personDir, { recursive: true, force: true });
          }
          const flatFile = path.join(dir, `${cleanKey}.jpg`);
          if (fs.existsSync(flatFile)) {
            fs.unlinkSync(flatFile);
          }
        } catch {
          // yoksay
        }
      }

      // 2. astro_memory.json'dan sil
      for (const memPath of MEMORY_FILE_PATHS) {
        try {
          if (fs.existsSync(memPath)) {
            const raw = fs.readFileSync(memPath, "utf-8");
            const mem = JSON.parse(raw);
            if (mem.known_people && mem.known_people[cleanKey]) {
              delete mem.known_people[cleanKey];
              fs.writeFileSync(memPath, JSON.stringify(mem, null, 2), "utf-8");
            }
          }
        } catch {
          // yoksay
        }
      }
    }
  } catch (e) {
    console.error("Kişi silme ek işlem hatası:", e);
  }

  revalidatePath("/panel/kisiler");
}

