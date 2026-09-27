"use client";

import { useTransition } from "react";
import { kisiKaldir } from "@/app/panel/kisiler/actions";

export function KisiSilDugmesi({ id, name }: { id: string; name: string }) {
  const [bekliyor, startTransition] = useTransition();

  return (
    <button
      type="button"
      className="btn btn--quiet btn--small"
      style={{ color: "var(--color-alarm, #ef4444)" }}
      disabled={bekliyor}
      onClick={() => {
        if (confirm(`'${name}' kaydını silmek istediğinize emin misiniz?`)) {
          startTransition(() => {
            void kisiKaldir(id);
          });
        }
      }}
    >
      {bekliyor ? "Siliniyor…" : "Sil"}
    </button>
  );
}
