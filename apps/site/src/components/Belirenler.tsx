"use client";

import { useEffect, useRef } from "react";

/**
 * Kaydırdıkça beliren parçaları saran kap.
 *
 * `reveal.ts` çerçeveden bağımsızdır ve değişmedi: içindeki `.reveal` sınıflı
 * elementleri bulup gözlemciye verir. Bir kere görünen bir daha gizlenmez —
 * ekranda gezinirken kartların tekrar tekrar belirip kaybolması sayfayı okunur
 * olmaktan çıkarıyordu.
 */
export function Belirenler({ children }: { children: React.ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const kap = ref.current;
    if (!kap) return;

    const hedefler = Array.from(kap.querySelectorAll<HTMLElement>(".reveal"));
    if (hedefler.length === 0) return;

    let iptal = false;
    void (async () => {
      const { observeReveals } = await import("@/site/reveal");
      if (iptal) return;
      const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      observeReveals(hedefler, reducedMotion);
    })();

    return () => {
      iptal = true;
    };
  }, []);

  return <div ref={ref}>{children}</div>;
}
