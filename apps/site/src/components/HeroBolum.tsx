"use client";

import { useEffect, useRef } from "react";

import { INTRO } from "@/data/icerik";

/**
 * Giriş bölümü ve açılış sahnesi.
 *
 * Metin `children` olarak sunucudan gelir: bölümün kendisi istemci bileşeni olsa
 * da başlık ve giriş paragrafı ham HTML yanıtında bulunur. Ölçüt buydu.
 *
 * Açılışın üç evresi sınıf değiştirerek yürür ve bu bilerek imperatif kaldı.
 * Evreleri React durumuna taşımak, CSS geçişlerinin sırasını değiştirir ve
 * ölçülmüş zamanlamayı (1800 ms bekleme + --intro-exit) yeniden ayarlamak
 * gerekirdi. Sıra şudur: yalnızca isim, isim çekilir, sonra model ve metin.
 */
export function HeroBolum({ children }: { children: React.ReactNode }) {
  const heroRef = useRef<HTMLElement>(null);
  const stageRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const hero = heroRef.current;
    const stage = stageRef.current;
    if (!hero || !stage) return;

    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    let iptal = false;
    let sahne: { stop(): void } | null = null;

    const govde = hero.querySelector<HTMLElement>(".hero__inner");

    const evre = (ad: "intro" | "exiting" | "settled"): void => {
      hero.classList.toggle("is-intro", ad === "intro");
      hero.classList.toggle("is-exiting", ad === "exiting");
      hero.classList.toggle("is-settled", ad === "settled");
      /*
       * Giriş sürerken metin odaklanabilir olmamalı: görünmeyen bir bağlantıya
       * sekme ile ulaşmak, ekranda hiçbir şey olmadan odağı kaybettirir.
       */
      if (govde) govde.inert = ad !== "settled";
    };

    const INTRO_HOLD_MS = 1800;
    const cikisSuresi =
      parseFloat(
        getComputedStyle(document.documentElement).getPropertyValue("--intro-exit"),
      ) || 500;

    let zamanlayici = 0;
    let bitti = false;

    const kaydirmaylaAtla = (): void => {
      if (window.scrollY > 24) bitir();
    };
    /* Arka plana alınan sekmede zamanlayıcılar kısılır; açılış orada takılmasın. */
    const gizlenmisseAtla = (): void => {
      if (document.hidden) bitir();
    };

    function bitir(): void {
      if (bitti) return;
      bitti = true;
      clearTimeout(zamanlayici);
      window.removeEventListener("scroll", kaydirmaylaAtla);
      document.removeEventListener("visibilitychange", gizlenmisseAtla);
      evre("settled");
    }

    if (reducedMotion || document.hidden || window.scrollY > 24 || window.location.hash) {
      bitir();
    } else {
      evre("intro");
      window.addEventListener("scroll", kaydirmaylaAtla, { passive: true });
      document.addEventListener("visibilitychange", gizlenmisseAtla);
      zamanlayici = window.setTimeout(() => {
        evre("exiting");
        zamanlayici = window.setTimeout(bitir, cikisSuresi);
      }, INTRO_HOLD_MS);
    }

    /*
     * Sıra sahneyi beklemez: model geç yüklense de metin zamanında gelir ve
     * sahne hazır olduğunda kendi yerine oturur.
     */
    void (async () => {
      try {
        const [{ createRobotScene }, { DemoDriver }] = await Promise.all([
          import("@/scene/robot-scene"),
          import("@astro/protocol"),
        ]);
        if (iptal) return;

        const s = await createRobotScene(stage, {
          // Dar ekranda sahnenin kendi ızgara satırı var; modeli ayrıca yukarı
          // itmek onu satırın üst kenarına yapıştırırdı.
          compactLift: false,
        });
        if (iptal) {
          s.stop();
          return;
        }
        s.setDriver(new DemoDriver());
        s.start();
        sahne = s;
      } catch (hata) {
        console.error("Giriş sahnesi yüklenemedi:", hata);
        stageFallback(stage);
        bitir();
      }
    })();

    return () => {
      iptal = true;
      bitir();
      sahne?.stop();
    };
  }, []);

  return (
    <section className="hero is-settled" ref={heroRef}>
      <div className="hero__stage" ref={stageRef} />

      <div className="intro" aria-hidden="true">
        <p className="intro__line">
          <span className="intro__kicker">{INTRO.kicker}</span>
          <span className="intro__name">{INTRO.name}</span>
        </p>
        <p className="intro__tail">{INTRO.tail}</p>
      </div>

      {children}
    </section>
  );
}

/** Sahne kurulamazsa sayfanın geri kalanı çalışmaya devam eder. */
function stageFallback(container: HTMLElement): void {
  container.querySelector("canvas")?.remove();

  const kutu = document.createElement("div");
  kutu.className = "stage-fallback";

  const ust = document.createElement("p");
  ust.className = "eyebrow";
  ust.textContent = "3B görünüm kullanılamıyor";

  const alt = document.createElement("p");
  alt.textContent = "Sayfanın geri kalanı etkilenmez.";

  kutu.append(ust, alt);
  container.appendChild(kutu);
}
