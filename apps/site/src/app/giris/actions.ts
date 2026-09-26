"use server";

import { APIError } from "better-auth/api";
import { headers } from "next/headers";
import { redirect } from "next/navigation";
import { z } from "zod";

import { auth } from "@/lib/auth";
import { guvenliDonusYolu } from "@/lib/yetki";

export interface GirisSonuc {
  ok: boolean;
  hata?: string;
}

const girdiSchema = z.object({
  eposta: z.email(),
  parola: z.string().min(1),
  devam: z.string().nullable(),
});

/**
 * Giriş.
 *
 * Sunucu eylemi: JavaScript kapalıyken de çalışır ve oturum çerezi sunucudan
 * yazılır.
 *
 * Hata mesajı hangi alanın yanlış olduğunu söylemiyor. "E-posta bulunamadı"
 * demek, hangi adreslerin kayıtlı olduğunu dışarıdan sınamaya izin verir.
 */
export async function girisYap(
  _onceki: GirisSonuc | null,
  form: FormData,
): Promise<GirisSonuc> {
  const cozulmus = girdiSchema.safeParse({
    eposta: form.get("eposta"),
    parola: form.get("parola"),
    devam: form.get("devam"),
  });

  if (!cozulmus.success) {
    return { ok: false, hata: "E-posta veya parola hatalı." };
  }

  try {
    await auth.api.signInEmail({
      body: { email: cozulmus.data.eposta, password: cozulmus.data.parola },
      headers: await headers(),
    });
  } catch (hata) {
    if (hata instanceof APIError) return { ok: false, hata: "E-posta veya parola hatalı." };
    throw hata;
  }

  redirect(guvenliDonusYolu(cozulmus.data.devam) as Parameters<typeof redirect>[0]);
}
