/**
 * E-posta gönderimi.
 *
 * Anahtar yoksa konsola yazar ve bunu **açıkça söyler**. Sessizce başarısız
 * olan bir e-posta, geliştirmede çalıştığını sanmaktan çok daha kötü: sorun
 * ancak üretimde, gerçek bir kullanıcı beklerken ortaya çıkıyor.
 */
export interface EpostaGirdi {
  kime: string;
  konu: string;
  govde: string;
}

export async function epostaGonder(girdi: EpostaGirdi): Promise<void> {
  const anahtar = process.env.RESEND_API_KEY;
  const gonderen = process.env.EPOSTA_GONDEREN ?? "ASTRO <bildirim@example.invalid>";

  if (!anahtar) {
    console.info(
      `[eposta] RESEND_API_KEY tanımlı değil — gönderilmedi, konsola yazıldı.\n` +
        `  kime : ${girdi.kime}\n  konu : ${girdi.konu}\n  gövde:\n${girdi.govde}\n`,
    );
    return;
  }

  const { Resend } = await import("resend");
  const resend = new Resend(anahtar);

  const { error } = await resend.emails.send({
    from: gonderen,
    to: girdi.kime,
    subject: girdi.konu,
    text: girdi.govde,
  });

  if (error) {
    // Çağıran taraf kararı kendisi verir: iletişim formunda kayıt yine durur,
    // parola sıfırlamada kullanıcıya hata gösterilir.
    throw new Error(`E-posta gönderilemedi: ${error.message}`);
  }
}
