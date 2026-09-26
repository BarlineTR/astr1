"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { signOut } from "@/lib/auth-client";

export function CikisDugmesi({ className = "btn" }: { className?: string }) {
  const router = useRouter();
  const [cikiliyor, setCikiliyor] = useState(false);

  return (
    <button
      className={className}
      type="button"
      disabled={cikiliyor}
      onClick={async () => {
        setCikiliyor(true);
        await signOut();
        /*
         * refresh() şart: sunucu bileşenleri önbellekte kaldığında çıkıştan
         * sonra panel bir an daha eski oturumla çiziliyordu.
         */
        router.push("/");
        router.refresh();
      }}
    >
      {cikiliyor ? "Çıkılıyor…" : "Çıkış"}
    </button>
  );
}
