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

let introTimer = 0;
let introFinished = false;

observeReveals(view.revealTargets, reducedMotion);
startIntro();
void mountHero();
watchShowcase();

/**
 * Açılış: önce yalnızca isim, sonra model.
 *
 * Model, isim ekranda dururken görünmez. İkisi aynı anda görünseydi dev
 * tipografi modelin üstüne biner ve ne yazı ne de model düzgün okunurdu.
 *
 * Sıra sahneyi beklemez: model geç yüklense de metin zamanında gelir, sahne
 * hazır olduğunda kendi yerine oturur.
 */
function startIntro(): void {
  if (reducedMotion || document.hidden || window.scrollY > 24 || window.location.hash) {
    finishIntro();
    return;
  }

  window.addEventListener("scroll", skipOnScroll, { passive: true });
  document.addEventListener("visibilitychange", skipWhenHidden);

  introTimer = window.setTimeout(() => {
    view.setPhase("exiting");
    introTimer = window.setTimeout(finishIntro, INTRO_EXIT_MS);
  }, INTRO_HOLD_MS);
}

/** Kullanıcı kaydırmaya başladıysa açılışı beklemesin. */
function skipOnScroll(): void {
  if (window.scrollY > 24) finishIntro();
}

/** Arka plana alınan sekmede zamanlayıcılar kısılır; açılış orada takılı kalmasın. */
function skipWhenHidden(): void {
  if (document.hidden) finishIntro();
}

function finishIntro(): void {
  if (introFinished) return;
  introFinished = true;
  clearTimeout(introTimer);
  window.removeEventListener("scroll", skipOnScroll);
  document.removeEventListener("visibilitychange", skipWhenHidden);
  view.setPhase("settled");
}

/**
 * Giriş sahnesi: modelin kendi anlatısını oynattığı canlı sahne.
 *
 * Model burada hareket eder — yavaşça döner ve senaryo sürücüsü kafayı sesin
 * geldiği yöne çevirir. Sabit olan şey hareket değil, sahnenin sayfadaki yeri:
 * bölüm akışta durduğu için kaydırınca metin modelin üstünden geçmez, ikisi
 * birlikte yukarı kayar.
 *
 * Bölüm ekrandan çıkınca çizim durur — sahnenin kendi görünürlük gözlemcisi
 * bunu hallediyor, sayfanın geri kalanı boyunca boşuna kare üretilmez.
 */
async function mountHero(): Promise<void> {
  try {
    const [{ createRobotScene }, { DemoDriver }] = await Promise.all([
      import("../scene/robot-scene"),
      import("../../../shared/demo-driver"),
    ]);

    const scene = await createRobotScene(view.heroStageEl, {
      // Dar ekranda sahnenin kendi ızgara satırı var; modeli ayrıca yukarı
      // itmek onu satırın üst kenarına yapıştırırdı.
      compactLift: false,
    });

    scene.setDriver(new DemoDriver());
    scene.start();
  } catch (error) {
    console.error("Giriş sahnesi yüklenemedi:", error);
    showStageFallback(view.heroStageEl);
    finishIntro();
  }
}

/**
 * Gösteri sahnesi yaklaşınca kurulur.
 *
 * İki sahne iki ayrı WebGL bağlamı demek. Gösteri hiç görülmeyecekse — ziyaretçi
 * giriş ekranından ayrılmadan çıkarsa — ikinci bağlamı hiç açmamak, özellikle
 * telefonda anlamlı bir kazanç. Yüklemeye bölüm ekrana girmeden başlanır ki
 * ziyaretçi oraya vardığında sahne hazır olsun.
 */
function watchShowcase(): void {
  if (reducedMotion || !("ResizeObserver" in window) || !("IntersectionObserver" in window)) {
    return;
  }

  const observer = new IntersectionObserver(
    (entries) => {
      if (!entries.some((entry) => entry.isIntersecting)) return;
      observer.disconnect();
      void mountShowcase();
    },
    { rootMargin: "120% 0px" },
  );

  observer.observe(view.showcaseEl);
}

async function mountShowcase(): Promise<void> {
  let scene: RobotScene;
  try {
    const { createRobotScene } = await import("../scene/robot-scene");
    scene = await createRobotScene(view.showcaseStageEl, {
      autoOrbit: false,
      interactive: false,
      // Gösteri kendi kutusundadır; dar ekranda modeli yukarı itmeye gerek yok.
      compactLift: false,
    });
    scene.start();
  } catch (error) {
    console.error("Gösteri sahnesi yüklenemedi:", error);
    showStageFallback(view.showcaseStageEl);
    return;
  }

  startShowcase({
    scene,
    steps: view.stepEls,
    markEl: view.markEl,
    markLabelEl: view.markLabelEl,
    stageEl: view.showcaseStageEl,
  });
}

/** Sahne kurulamazsa sayfanın geri kalanı çalışmaya devam eder. */
function showStageFallback(container: HTMLElement): void {
  container.querySelector("canvas")?.remove();
  container.appendChild(
    el(
      "div",
      { class: "stage-fallback" },
      el("p", { class: "eyebrow" }, "3B görünüm kullanılamıyor"),
      el("p", {}, "Sayfanın geri kalanı etkilenmez."),
    ),
  );
}
