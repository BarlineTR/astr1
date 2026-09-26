"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";

import { signIn } from "@/lib/auth-client";
import { guvenliDonusYolu } from "@/lib/yetki";

export function GirisFormu() {
  const router = useRouter();
  const aramaParams = useSearchParams();
  const [hata, setHata] = useState<string | null>(null);
  const [gonderiliyor, setGonderiliyor] = useState(false);

  async function gonder(olay: React.FormEvent<HTMLFormElement>) {
    olay.preventDefault();
    setHata(null);
    setGonderiliyor(true);

    const form = new FormData(olay.currentTarget);
    const sonuc = await signIn.email({
      email: String(form.get("eposta") ?? ""),
      password: String(form.get("parola") ?? ""),
    });

    if (sonuc.error) {
      /*
       * Sağlayıcının İngilizce mesajı gösterilmiyor ve hangi alanın yanlış
       * olduğu da söylenmiyor: "e-posta bulunamadı" demek, hangi adreslerin
       * kayıtlı olduğunu dışarıdan sınamaya izin verir.
       */
      setHata("E-posta veya parola hatalı.");
      setGonderiliyor(false);
      return;
    }

    /*
     * typedRoutes derleme anında sabit adresleri doğruluyor; buradaki adres
     * çalışma zamanında geliyor ve güvenliği guvenliDonusYolu sağlıyor
     * (dış adres ve protokolsüz biçim reddediliyor). Tip bu yüzden daraltılıyor.
     */
    router.push(
      guvenliDonusYolu(aramaParams.get("devam")) as Parameters<typeof router.push>[0],
    );
    router.refresh();
  }

  return (
    <form className="form" onSubmit={gonder} noValidate>
      {hata && (
        <p className="form__hata" role="alert">
          {hata}
        </p>
      )}

      <label className="form__alan">
        <span>E-posta</span>
        <input type="email" name="eposta" autoComplete="email" required />
      </label>

      <label className="form__alan">
        <span>Parola</span>
        <input type="password" name="parola" autoComplete="current-password" required />
      </label>

      <button className="btn btn--primary" type="submit" disabled={gonderiliyor}>
        {gonderiliyor ? "Giriş yapılıyor…" : "Giriş yap"}
      </button>
    </form>
  );
}
