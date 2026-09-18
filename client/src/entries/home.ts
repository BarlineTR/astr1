import "../styles/tokens.css";
import "../styles/base.css";
import "../styles/layout.css";

import { el } from "../dom";
import { renderHome } from "../pages/home";
import { observeReveals } from "../site/reveal";
import { startShowcase } from "../site/showcase";
import type { RobotScene } from "../scene/robot-scene";

const root = document.querySelector<HTMLElement>("#app");
if (!root) throw new Error("#app bulunamadı");

const view = renderHome(root);
const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
const motion = getComputedStyle(document.documentElement);
const INTRO_HOLD_MS = 1800;
const INTRO_EXIT_MS = parseFloat(motion.getPropertyValue("--intro-exit"));
const SETTLE_MS = parseFloat(motion.getPropertyValue("--intro-settle"));
let scene: RobotScene | null = null;
let composition = 0;
let introFrame = 0;
let introTimer = 0;
let introFinished = false;

observeReveals(view.revealTargets, reducedMotion);
startIntro();
void mountScene();

/** Metin modeli beklemez; geç yüklenen sahne o anki kompozisyona katılır. */
function startIntro(): void {
  if (reducedMotion || document.hidden || window.scrollY > 24 || window.location.hash) {
    finishIntro();
    return;
  }
  window.addEventListener("scroll", skipOnScroll, { passive: true });
  document.addEventListener("visibilitychange", skipWhenHidden);
  introTimer = window.setTimeout(() => {
    view.setPhase("exiting");
    introTimer = window.setTimeout(() => {
      view.setPhase("settled");
      const start = performance.now();
      const step = (now: number): void => {
        const t = Math.min((now - start) / SETTLE_MS, 1);
        // CSS --ease-scene ile aynı kübik çıkış eğrisi.
        composition = 1 - Math.pow(1 - t, 3);
        scene?.setComposition(composition);
        if (t < 1) introFrame = requestAnimationFrame(step);
        else finishIntro();
      };
      introFrame = requestAnimationFrame(step);
    }, INTRO_EXIT_MS);
  }, INTRO_HOLD_MS);
}

function skipOnScroll(): void {
  if (window.scrollY > 24) finishIntro();
}

function skipWhenHidden(): void {
  if (document.hidden) finishIntro();
}

function finishIntro(): void {
  if (introFinished) return;
  introFinished = true;
  clearTimeout(introTimer);
  cancelAnimationFrame(introFrame);
  window.removeEventListener("scroll", skipOnScroll);
  document.removeEventListener("visibilitychange", skipWhenHidden);
  view.setPhase("settled");
  composition = 1;
  scene?.setComposition(1);
}

async function mountScene(): Promise<void> {
  try {
    const [{ createRobotScene }, { DemoDriver }] = await Promise.all([
      import("../scene/robot-scene"),
      import("../../../shared/demo-driver"),
    ]);
    scene = await createRobotScene(view.stageEl, {
      offsetSubject: composition === 1,
      autoOrbit: false,
    });
    scene.setComposition(composition);
    if (!reducedMotion) scene.setDriver(new DemoDriver());
    scene.start();

    // Azaltılmış harekette sabit model ve her zaman okunabilir metinler.
    // Gösteri, metnin yeniden akışını yakalamak için ResizeObserver kullanır;
    // desteklenmeyen tarayıcıda hiç başlatılmaz ve adımlar düz metin kalır.
    if (!reducedMotion && "ResizeObserver" in window) {
      startShowcase({
        scene,
        steps: view.stepEls,
        markEl: view.markEl,
        markLabelEl: view.markLabelEl,
        stageEl: view.stageEl,
      });
    }
  } catch (error) {
    console.error("3B sahne yüklenemedi:", error);
    view.stageEl.querySelector("canvas")?.remove();
    view.stageEl.appendChild(
      el(
        "div",
        { class: "stage-fallback" },
        el("p", { class: "eyebrow" }, "3B görünüm kullanılamıyor"),
        el("p", {}, "Sayfanın geri kalanı etkilenmez."),
      ),
    );
    finishIntro();
  }
}
