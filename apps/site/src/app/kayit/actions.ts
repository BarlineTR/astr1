"use server";

import { randomUUID } from "node:crypto";

import { APIError } from "better-auth/api";
import { headers } from "next/headers";
import { redirect } from "next/navigation";
import { z } from "zod";

import { db } from "@/db";
import { consents } from "@/db/schema";
import { KVKK_METIN_SURUMU } from "@/data/hukuki";
import { auth } from "@/lib/auth";

export interface KayitSonuc {
  ok: boolean;
  hatalar?: Record<string, string>;
}

const girdiSchema = z.object({
  ad: z.string().trim().min(2, "Adınızı yazın.").max(120),
  eposta: z.email("Geçerli bir e-posta adresi yazın.").max(200),
  parola: z.string().min(10, "Parola en az 10 karakter olmalı.").max(200),
  kvkkOnay: z.boolean().refine((v) => v, {
    message: "Devam etmek için KVKK aydınlatma metnini onaylamanız gerekiyor.",
  }),
});

/**
 * Hesap açar ve KVKK onayını aynı akışta kaydeder.
 *
 * Önce istemci tarafında iki adımdı: `signUp.email()` ve ardından ayrı bir
 * `fetch("/api/onay")`. İkinci istek takıldığında yönlendirme hiç çalışmıyor,
 * kullanıcı **hesabı açılmış olmasına rağmen** kayıt sayfasında kalıyor ve
 * hiçbir geri bildirim almıyordu; tekrar denediğinde "bu e-posta zaten var"
 * hatası alıyordu. Paralel testlerde beşte ikisi böyle düşüyordu.
 *
 * Sunucu eylemi olarak yazıldığı için ayrıca JavaScript kapalıyken de çalışıyor
 * ve onay kutusu artık sunucuda zorunlu — asıl olması gereken yer orası.
 */
export async function kayitOl(
  _onceki: KayitSonuc | null,
  form: FormData,
): Promise<KayitSonuc> {
  const cozulmus = girdiSchema.safeParse({
    ad: form.get("ad"),
    eposta: form.get("eposta"),
    parola: form.get("parola"),
    kvkkOnay: form.get("kvkkOnay") === "on",
  });

  if (!cozulmus.success) {
    const hatalar: Record<string, string> = {};
    for (const sorun of cozulmus.error.issues) {
      const alan = String(sorun.path[0] ?? "genel");
      hatalar[alan] ??= sorun.message;
    }
    return { ok: false, hatalar };
  }

  const { ad, eposta, parola } = cozulmus.data;
  const basliklar = await headers();

  let kullaniciId: string;
  try {
    const sonuc = await auth.api.signUpEmail({
      body: { name: ad, email: eposta, password: parola },
      headers: basliklar,
    });
    kullaniciId = sonuc.user.id;
  } catch (hata) {
    if (hata instanceof APIError) {
      return {
        ok: false,
        hatalar: {
          eposta:
            hata.status === "UNPROCESSABLE_ENTITY"
              ? "Bu e-posta adresiyle bir hesap zaten var."
              : "Hesap oluşturulamadı. Lütfen bilgileri kontrol edin.",
        },
      };
    }
    throw hata;
  }

  await db.insert(consents).values({
    id: randomUUID(),
    userId: kullaniciId,
    kind: "kvkk",
    textVersion: KVKK_METIN_SURUMU,
    ipAddress: basliklar.get("x-forwarded-for")?.split(",")[0]?.trim() ?? null,
    userAgent: basliklar.get("user-agent") ?? null,
  });

  // redirect() NEXT_REDIRECT fırlatır; try/catch dışında olmalı.
  redirect("/panel");
}
