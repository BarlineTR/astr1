"use client";

import { useState } from "react";

/**
 * Taklit ödeme kararı.
 *
 * Gerçek akışta iyzico geri dönüş adresimize token POST eder; burada aynısını
 * tarayıcıdan yapıyoruz ki sonraki bütün adımlar (sonuç alma, idempotensi,
 * sipariş durumu) gerçeğiyle aynı yolu izlesin.
 */
export function SahteOdemeFormu({ token }: { token: string }) {
  const [bekliyor, setBekliyor] = useState(false);

  async function karar(sonuc: "basarili" | "basarisiz") {
    setBekliyor(true);
    await fetch("/api/odeme/sahte-karar", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ token, sonuc }),
    });

    // Gerçek sağlayıcının yaptığının aynısı: geri dönüş adresine token POST'u.
    const form = document.createElement("form");
    form.method = "POST";
    form.action = "/api/odeme/geri-donus";
    const alan = document.createElement("input");
    alan.name = "token";
    alan.value = token;
    form.appendChild(alan);
    document.body.appendChild(form);
    form.submit();
  }

  return (
    <div className="controls" style={{ marginTop: "2rem" }}>
      <button
        className="btn btn--primary"
        type="button"
        disabled={bekliyor}
        onClick={() => karar("basarili")}
      >
        Ödemeyi onayla
      </button>
      <button
        className="btn btn--alarm"
        type="button"
        disabled={bekliyor}
        onClick={() => karar("basarisiz")}
      >
        Ödemeyi reddet
      </button>
    </div>
  );
}
