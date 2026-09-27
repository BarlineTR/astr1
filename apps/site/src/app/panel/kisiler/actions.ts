"use server";

import { revalidatePath } from "next/cache";
import { kisiEkle, kisiSil } from "@/db/sorgular/kisiler";
import { oturumGerekli } from "@/lib/oturum";
import type { KisiRol } from "@/db/schema";

export interface KisiKaydetSonuc {
  ok: boolean;
  hata?: string;
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
    revalidatePath("/panel/kisiler");
    return { ok: true };
  } catch (err) {
    console.error("Kişi ekleme hatası:", err);
    return { ok: false, hata: "Kişi kaydedilemedi. Lütfen tekrar deneyin." };
  }
}

export async function kisiKaldir(id: string) {
  const oturum = await oturumGerekli("/panel/kisiler");
  await kisiSil(id, oturum.user.id);
  revalidatePath("/panel/kisiler");
}
