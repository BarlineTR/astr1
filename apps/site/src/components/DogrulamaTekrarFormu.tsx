"use client";

import { useActionState } from "react";
import { dogrulamaEpostasiTekrarGonder, type TekrarGonderSonuc } from "@/app/dogrulama-bekleniyor/actions";

export function DogrulamaTekrarFormu({ eposta }: { eposta: string }) {
  const [durum, eylem, bekliyor] = useActionState<TekrarGonderSonuc | null, FormData>(
    dogrulamaEpostasiTekrarGonder,
    null,
  );

  return (
    <form action={eylem} className="form">
      <input type="hidden" name="eposta" value={eposta} />
      {durum?.mesaj && (
        <p className="form__basari" role="status" style={{ color: "var(--color-success, #10b981)" }}>
          {durum.mesaj}
        </p>
      )}
      {durum?.hata && (
        <p className="form__hata" role="alert">
          {durum.hata}
        </p>
      )}
      <button className="btn btn--quiet" type="submit" disabled={bekliyor}>
        {bekliyor ? "Gönderiliyor…" : "Doğrulama e-postasını tekrar gönder"}
      </button>
    </form>
  );
}
