import * as THREE from "three";

import { SHOWCASE } from "../data/content";
import type { RobotScene } from "../scene/robot-scene";

/**
 * Özellikleri modelin üzerinde tek tek gösteren kaydırma anlatısı.
 *
 * Sahne sabit kalır (yapışkan), metin adımları onun üzerinden akar. Ekranın
 * ortasına gelen adım etkin sayılır; kamera o adımın çapasına yaklaşır ve model
 * üstünde bir işaret belirir.
 *
 * Etkin adımı seçmek için kaydırma olayı dinlenmez: her karede konum hesaplamak
 * gereksiz iş demek olurdu. Bunun yerine ekranın ortasına daraltılmış bir
 * gözlem alanı kullanılır — bir adım bu bandı kestiğinde etkin olur.
 */
export interface ShowcaseController {
  stop(): void;
}

export function startShowcase(options: {
  scene: RobotScene;
  steps: HTMLElement[];
  markEl: HTMLElement;
  markLabelEl: HTMLElement;
  stageEl: HTMLElement;
}): ShowcaseController {
  const { scene, steps, markEl, markLabelEl, stageEl } = options;
  const { height, radius } = scene.metrics;

  /** Oransal çapaları modelin gerçek ölçülerine çevirir. */
  const anchors = SHOWCASE.map(
    (step) =>
      new THREE.Vector3(step.anchor.x * radius, step.anchor.y * height, step.anchor.z * radius),
  );

  let active = -1;

  const setActive = (index: number): void => {
    if (index === active) return;
    active = index;

    for (const [i, step] of steps.entries()) {
      step.classList.toggle("is-active", i === index);
    }

    if (index < 0) {
      scene.focus(null);
      markEl.classList.remove("is-visible");
      return;
    }

    const step = SHOWCASE[index]!;
    const anchor = anchors[index]!;
    scene.focus({
      point: anchor,
      azimuthDeg: step.camera.azimuthDeg,
      polarDeg: step.camera.polarDeg,
      distance: step.camera.distanceScale * height,
    });

    markLabelEl.textContent = step.label;
    markEl.classList.add("is-visible");
  };

  const observer = new IntersectionObserver(
    (entries) => {
      for (const entry of entries) {
        const index = steps.indexOf(entry.target as HTMLElement);
        if (index === -1) continue;
        if (entry.isIntersecting) setActive(index);
        else if (index === active) setActive(-1);
      }
    },
    // Ekranın ortasındaki dar bant: adım tam ortaya geldiğinde etkinleşir.
    { rootMargin: "-45% 0px -45% 0px", threshold: 0 },
  );

  for (const step of steps) observer.observe(step);

  /*
   * Adım metinleri yalnızca gösteri gerçekten çalışırken gizlenir.
   *
   * Gizleme CSS'te koşulsuz yapılsaydı ve gösteri hiç başlamasaydı — sahne
   * yüklenemediğinde ya da tarayıcı gözlemciyi desteklemediğinde — bütün özellik
   * metinleri kalıcı olarak görünmez kalırdı. Bu işaret, gizlemeyi ancak
   * denetleyici ayaktayken açar.
   */
  const list = steps[0]?.parentElement;
  list?.classList.add("is-driven");

  // İşaret her karede güncellenir: kamera hareket ettikçe çapanın ekrandaki
  // yeri de değişir, sabit bir konum bir kare sonra yanlış olurdu.
  scene.onFrame(() => {
    if (active < 0) return;
    const anchor = anchors[active];
    if (!anchor) return;

    const projected = scene.project(anchor);
    const inside =
      projected.inFront &&
      projected.x > 0 &&
      projected.y > 0 &&
      projected.x < stageEl.clientWidth &&
      projected.y < stageEl.clientHeight;

    markEl.classList.toggle("is-offscreen", !inside);
    markEl.style.transform = `translate3d(${projected.x}px, ${projected.y}px, 0)`;
  });

  return {
    stop() {
      list?.classList.remove("is-driven");
      observer.disconnect();
      scene.onFrame(null);
      scene.focus(null);
    },
  };
}
