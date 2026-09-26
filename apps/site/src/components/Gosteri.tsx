"use client";

import { useEffect, useRef } from "react";

import { SHOWCASE } from "@/data/icerik";

/**
 * Özellikleri modelin üzerinde tek tek gösteren kaydırma anlatısı.
 *
 * Adım metinlerinin tamamı **sunucuda** çizilir: SEO'nun asıl kazandığı yer
 * burasıdır, altı özellik ham HTML'de bulunur. İstemcinin yaptığı tek şey
 * sahneyi kurup `startShowcase`e elementleri vermek.
 *
 * `showcase.ts` çerçeveden bağımsızdır ve taşıma sırasında hiç değişmedi; kendi
 * 10 testi de değişmeden geçiyor. Buradaki sınıf adları `layout.css` ve o
 * modülle birebir eşleşmek zorunda.
 */
export function Gosteri() {
  const bolumRef = useRef<HTMLElement>(null);
  const stageRef = useRef<HTMLDivElement>(null);
  const markRef = useRef<HTMLDivElement>(null);
  const markLabelRef = useRef<HTMLSpanElement>(null);
  const stepRefs = useRef<Array<HTMLLIElement | null>>([]);

  useEffect(() => {
    const bolum = bolumRef.current;
    const stage = stageRef.current;
    const markEl = markRef.current;
    const markLabelEl = markLabelRef.current;
    const steps = stepRefs.current.filter((x): x is HTMLLIElement => x !== null);
    if (!bolum || !stage || !markEl || !markLabelEl || steps.length === 0) return;

    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    if (!("ResizeObserver" in window) || !("IntersectionObserver" in window)) return;

    let kontrol: { stop(): void } | null = null;
    let sahne: { stop(): void } | null = null;
    let iptal = false;

    /*
     * İki sahne iki ayrı WebGL bağlamı demek. Ziyaretçi giriş ekranından
     * ayrılmadan çıkarsa ikinci bağlam hiç açılmasın — özellikle telefonda
     * anlamlı bir kazanç. Yüklemeye bölüm ekrana girmeden başlanır ki ziyaretçi
     * oraya vardığında sahne hazır olsun.
     */
    const gozlemci = new IntersectionObserver(
      (girisler) => {
        if (!girisler.some((g) => g.isIntersecting)) return;
        gozlemci.disconnect();

        void (async () => {
          try {
            const [{ createRobotScene }, { startShowcase }] = await Promise.all([
              import("@/scene/robot-scene"),
              import("@/site/showcase"),
            ]);
            if (iptal) return;

            const s = await createRobotScene(stage, {
              autoOrbit: false,
              interactive: false,
              // Gösteri kendi kutusundadır; dar ekranda modeli yukarı itmeye
              // gerek yok.
              compactLift: false,
            });
            if (iptal) {
              s.stop();
              return;
            }
            s.start();
            sahne = s;
            kontrol = startShowcase({
              scene: s,
              steps,
              markEl,
              markLabelEl,
              stageEl: stage,
            });
          } catch (hata) {
            console.error("Gösteri sahnesi yüklenemedi:", hata);
          }
        })();
      },
      { rootMargin: "120% 0px" },
    );

    gozlemci.observe(bolum);

    return () => {
      iptal = true;
      gozlemci.disconnect();
      kontrol?.stop();
      sahne?.stop();
    };
  }, []);

  return (
    <section className="showcase" ref={bolumRef}>
      <div className="showcase__sticky">
        <div className="showcase__stage" ref={stageRef} />
        <div className="mark" aria-hidden="true" ref={markRef}>
          <span className="mark__ring" />
          <span className="mark__stem" />
          <span className="mark__label" ref={markLabelRef} />
        </div>
      </div>

      <ol className="showcase__steps">
        {SHOWCASE.map((step, i) => (
          <li
            key={step.id}
            className="step"
            id={i === 0 ? "ozellikler" : step.id}
            ref={(el) => {
              stepRefs.current[i] = el;
            }}
          >
            <div className="page step__inner">
              <p className="step__index mono">
                {String(i + 1).padStart(2, "0")} / {String(SHOWCASE.length).padStart(2, "0")}
              </p>
              <h2 className="step__title">{step.title}</h2>
              <p className="step__body">{step.body}</p>
            </div>
          </li>
        ))}
      </ol>
    </section>
  );
}
