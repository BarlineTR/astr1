"use client";

import { useRouter } from "next/navigation";
import Link from "next/link";
import { useState } from "react";

import { signUp } from "@/lib/auth-client";
import { KVKK_METIN_SURUMU } from "@/data/hukuki";

export function KayitFormu() {
  const router = useRouter();
  const [hata, setHata] = useState<string | null>(null);
  const [gonderiliyor, setGonderiliyor] = useState(false);

  async function gonder(olay: React.FormEvent<HTMLFormElement>) {
    olay.preventDefault();
    setHata(null);

    const form = new FormData(olay.currentTarget);
    const onay = form.get("kvkk") === "on";

    /*
     * Onay istemcide de sunucuda da zorunlu. Buradaki kontrol yalnızca hızlı
     * geri bildirim; asıl engel sunucu tarafındaki onay kaydıdır.
     */
    if (!onay) {
      setHata("Devam etmek için KVKK aydınlatma metnini onaylamanız gerekiyor.");
      return;
    }

    const parola = String(form.get("parola") ?? "");
    if (parola.length < 10) {
      setHata("Parola en az 10 karakter olmalı.");
      return;
    }

    setGonderiliyor(true);

    const sonuc = await signUp.email({
      name: String(form.get("ad") ?? ""),
      email: String(form.get("eposta") ?? ""),
      password: parola,
    });

    if (sonuc.error) {
      setHata(
        sonuc.error.status === 422
          ? "Bu e-posta adresiyle bir hesap zaten var."
          : "Hesap oluşturulamadı. Lütfen bilgileri kontrol edin.",
      );
      setGonderiliyor(false);
      return;
    }

    // Onay kaydı sunucuya yazılır; hangi metin sürümüne verildiği ile birlikte.
    await fetch("/api/onay", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ kind: "kvkk", textVersion: KVKK_METIN_SURUMU }),
    });

    router.push("/panel");
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
        <span>Ad soyad</span>
        <input type="text" name="ad" autoComplete="name" required />
      </label>

      <label className="form__alan">
        <span>E-posta</span>
        <input type="email" name="eposta" autoComplete="email" required />
      </label>

      {/*
        İpucu etiketin içinde değil: label'ın içindeki her metin erişilebilir
        ada katılıyor ve alan "Parola En az 10 karakter." diye okunuyordu.
        aria-describedby doğru bağ.
      */}
      <div className="form__alan">
        <label htmlFor="parola">Parola</label>
        <input
          id="parola"
          type="password"
          name="parola"
          autoComplete="new-password"
          aria-describedby="parola-ipucu"
          required
          minLength={10}
        />
        <small className="form__ipucu" id="parola-ipucu">
          En az 10 karakter.
        </small>
      </div>

      <label className="form__onay">
        <input type="checkbox" name="kvkk" />
        <span>
          <Link href="/kvkk">KVKK aydınlatma metnini</Link> okudum, kişisel verilerimin
          işlenmesini kabul ediyorum.
        </span>
      </label>

      <button className="btn btn--primary" type="submit" disabled={gonderiliyor}>
        {gonderiliyor ? "Hesap oluşturuluyor…" : "Hesap oluştur"}
      </button>
    </form>
  );
}
