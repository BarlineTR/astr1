import "../styles/tokens.css";
import "../styles/base.css";
import "../styles/layout.css";

import { el } from "../dom";
import { renderHome } from "../pages/home";
import { observeReveals } from "../site/reveal";
import { startShowcase } from "../site/showcase";

const root = document.querySelector<HTMLElement>("#app");
if (!root) throw new Error("#app bulunamadı");

const view = renderHome(root);
const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

observeReveals(view.revealTargets, reducedMotion);
void mountScene();

/**
 * Açılış: önce isim, sonra yerleşme.
 *
 * Sıra CSS'te değil burada kurulur, çünkü model sahnesinin kompozisyonu da aynı
 * anda kaymalı — metin sola gelirken model sağa gidiyor. İki hareketin aynı
 * süreyi paylaşması gerekiyor, bu yüzden tek yerden sürülüyorlar.
 *
 * Hareket azaltma tercihinde animasyon hiç oynatılmaz: sayfa doğrudan yerleşmiş
 * halinde açılır.
 */
/** İsmin ekranda durduğu süre. */
const INTRO_HOLD_MS = 1400;
/** İsmin silinme süresi. CSS'teki `.intro` geçişiyle aynı olmalı. */
const INTRO_EXIT_MS = 700;
/** Metnin ve modelin yerleşme süresi. */
const SETTLE_MS = 1000;

async function mountScene(): Promise<void> {
  if (reducedMotion) view.setPhase("settled");

  let scene: Awaited<ReturnType<typeof import("../scene/robot-scene").createRobotScene>> | null = null;

  try {
    const [{ createRobotScene }, { DemoDriver }] = await Promise.all([
      import("../scene/robot-scene"),
      import("../../../shared/demo-driver"),
    ]);
    scene = await createRobotScene(view.stageEl, {
      offsetSubject: reducedMotion,
    });
    scene.setDriver(new DemoDriver());
    scene.start();

    // Özellik anlatısı sahneye bağlıdır: sahne yoksa adımlar düz metin olarak
    // okunmaya devam eder, yalnızca kamera ve işaret çalışmaz.
    startShowcase({
      scene,
      steps: view.stepEls,
      markEl: view.markEl,
      markLabelEl: view.markLabelEl,
      stageEl: view.stageEl,
    });
  } catch (error) {
    console.error("3B sahne yüklenemedi:", error);
    view.stageEl.appendChild(
      el(
        "div",
        { class: "stage-fallback" },
        el("p", { class: "eyebrow" }, "3B görünüm kullanılamıyor"),
        el("p", {}, "Sayfanın geri kalanı etkilenmez."),
      ),
    );
  }

  if (reducedMotion) return;

  // Sahne yüklenemese bile metin gelmeli: beklemeler her durumda işler.
  window.setTimeout(() => {
    view.setPhase("exiting");

    // Metin ve model, isim tamamen silindikten sonra hareket eder.
    window.setTimeout(() => {
      view.setPhase("settled");
      if (scene) slideSubject(scene);
    }, INTRO_EXIT_MS);
  }, INTRO_HOLD_MS);
}

/** Modeli ortadan sağa, metnin girişiyle aynı sürede taşır. */
function slideSubject(scene: { setComposition(amount: number): void }): void {
  const start = performance.now();
  const step = (now: number): void => {
    const t = Math.min((now - start) / SETTLE_MS, 1);
    // Metnin CSS geçişiyle aynı yumuşama eğrisi.
    const eased = 1 - Math.pow(1 - t, 3);
    scene.setComposition(eased);
    if (t < 1) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);

  /*
   * Son değer ayrıca garanti altına alınır.
   *
   * `requestAnimationFrame` yalnızca sayfa görünürken çalışır. Sayfa arka plan
   * sekmesinde açılırsa yukarıdaki zincir hiç başlamaz ve model, metin çoktan
   * gelmişken ortada asılı kalır. Bu zamanlayıcı arka planda da işlediği için
   * kompozisyon her koşulda doğru yerde biter.
   */
  window.setTimeout(() => scene.setComposition(1), SETTLE_MS + 150);
}
