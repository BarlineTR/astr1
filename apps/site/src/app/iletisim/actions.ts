"use server";

import { randomUUID } from "node:crypto";

import { headers } from "next/headers";

import { db } from "@/db";
import { consents, contactRequests } from "@/db/schema";
import { KVKK_METIN_SURUMU } from "@/data/hukuki";
import { epostaGonder } from "@/lib/eposta";
import { iletisimSchema } from "@/lib/iletisim-sema";

export interface GonderSonuc {
  ok: boolean;
  /** Alan adı → hata mesajı. */
  hatalar?: Record<string, string>;
  genelHata?: string;
}

/**
 * İletişim / teklif talebi.
 *
 * Sunucu eylemi olarak yazıldı: JavaScript kapalıyken de form gönderilebiliyor.
 * Doğrulama burada yapılır; istemci doğrulaması yalnızca hızlı geri bildirim.
 */
export async function iletisimGonder(
  _oncekiDurum: GonderSonuc | null,
  form: FormData,
): Promise<GonderSonuc> {
  const cozulmus = iletisimSchema.safeParse({
    tur: form.get("tur"),
    ad: form.get("ad"),
    eposta: form.get("eposta"),
    sirket: form.get("sirket") || undefined,
    telefon: form.get("telefon") || undefined,
    mesaj: form.get("mesaj"),
    kvkkOnay: form.get("kvkkOnay") === "on",
    kaynakSayfa: form.get("kaynakSayfa")?.toString() || undefined,
    website: form.get("website")?.toString() || undefined,
  });

  if (!cozulmus.success) {
    const hatalar: Record<string, string> = {};
    for (const sorun of cozulmus.error.issues) {
      const alan = String(sorun.path[0] ?? "genel");
      hatalar[alan] ??= sorun.message;
    }
    return { ok: false, hatalar };
  }

  const veri = cozulmus.data;
  const basliklar = await headers();
  const ip = basliklar.get("x-forwarded-for")?.split(",")[0]?.trim() ?? null;

  const talepId = randomUUID();

  await db.insert(contactRequests).values({
    id: talepId,
    kind: veri.tur,
    name: veri.ad,
    email: veri.eposta,
    company: veri.sirket ?? null,
    phone: veri.telefon ?? null,
    message: veri.mesaj,
    sourcePage: veri.kaynakSayfa ?? null,
  });

  // Onay, verildiği metin sürümüyle birlikte kaydedilir.
  await db.insert(consents).values({
    id: randomUUID(),
    userId: null,
    kind: "kvkk",
    textVersion: KVKK_METIN_SURUMU,
    ipAddress: ip,
    userAgent: basliklar.get("user-agent") ?? null,
  });

  /*
   * E-posta bildirimi başarısız olsa bile talep kayıtlı kalır ve kullanıcıya
   * başarı gösterilir: talep alınmıştır, e-posta yalnızca bizim haberdar olma
   * yolumuz. Hatayı yutmuyoruz, kaydediyoruz.
   */
  try {
    await epostaGonder({
      kime: process.env.EPOSTA_ALICI ?? "iletisim@example.invalid",
      konu: `${veri.tur === "teklif" ? "Teklif talebi" : "İletişim"} — ${veri.ad}`,
      govde:
        `Tür    : ${veri.tur}\n` +
        `Ad     : ${veri.ad}\n` +
        `E-posta: ${veri.eposta}\n` +
        `Kurum  : ${veri.sirket ?? "—"}\n` +
        `Telefon: ${veri.telefon ?? "—"}\n` +
        `Sayfa  : ${veri.kaynakSayfa ?? "—"}\n` +
        `Kayıt  : ${talepId}\n\n${veri.mesaj}\n`,
    });
  } catch (hata) {
    console.error("[iletisim] bildirim e-postası gönderilemedi:", hata);
  }

  return { ok: true };
}
