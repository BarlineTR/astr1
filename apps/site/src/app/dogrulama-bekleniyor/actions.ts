"use server";

import { headers } from "next/headers";
import { auth } from "@/lib/auth";

export interface TekrarGonderSonuc {
  ok: boolean;
  mesaj?: string;
  hata?: string;
}

export async function dogrulamaEpostasiTekrarGonder(
  _onceki: TekrarGonderSonuc | null,
  form: FormData,
): Promise<TekrarGonderSonuc> {
  const eposta = String(form.get("eposta") ?? "").trim();
  if (!eposta) {
    return { ok: false, hata: "E-posta adresi belirtilmedi." };
  }

  try {
    const basliklar = await headers();
    await auth.api.sendVerificationEmail({
      body: { email: eposta },
      headers: basliklar,
    });
    return { ok: true, mesaj: "Doğrulama bağlantısı e-posta adresinize tekrar gönderildi." };
  } catch (hata) {
    console.error("Doğrulama e-postası tekrar gönderilemedi:", hata);
    return { ok: false, hata: "E-posta gönderilemedi. Lütfen biraz sonra tekrar deneyin." };
  }
}
