import { CLOSING, FEATURES, FIGURES, HERO, INTRO, SHOWCASE, SITE } from "../data/content";
import { el } from "../dom";
import { footer, header } from "../site/chrome";

/**
 * Açılışın üç evresi.
 *
 * `exiting` ayrı bir evre, çünkü isim ile sahnenin geçişleri aynı anda başlarsa
 * üst üste binerler: "ASTRO" daha silinmeden model arkasında belirir. Sıra
 * şudur — yalnızca isim, isim çekilir, sonra model ve metin gelir.
 */
export type IntroPhase = "intro" | "exiting" | "settled";

export interface HomeView {
  /** Giriş bölümünün kendi sahnesi. Sabit durur, hareket etmez. */
  heroStageEl: HTMLElement;
  /** Özellik gösterisinin kendi sahnesi. Adımlara göre hareket eder. */
  showcaseEl: HTMLElement;
  showcaseStageEl: HTMLElement;
  markEl: HTMLElement;
  markLabelEl: HTMLElement;
  stepEls: HTMLElement[];
  setPhase(phase: IntroPhase): void;
  revealTargets: HTMLElement[];
}

/**
 * Ana sayfa.
 *
 * Giriş ve özellik gösterisi birbirinden bağımsız iki bölümdür ve her birinin
 * kendi 3B sahnesi vardır.
 *
 * Tek bir yapışkan tuval paylaşıldığında iki sorun çıkıyordu: giriş metni ve
 * rakam şeridi yukarı kayarken sabit duran modelin ortasından geçiyor, ve
 * girişin sakin duruşu ile gösterinin kamera hareketi aynı sahneyi çekiştiriyordu.
 * Ayrı bölümler bunu yapısal olarak çözer — giriş akışta kayar, gösteri kendi
 * içinde yapışır.
 */
export function renderHome(root: HTMLElement): HomeView {
  const heroStageEl = el("div", { class: "hero__stage" });
  const showcaseStageEl = el("div", { class: "showcase__stage" });

  const markLabelEl = el("span", { class: "mark__label" });
  const markEl = el(
    "div",
    { class: "mark", "aria-hidden": "true" },
    el("span", { class: "mark__ring" }),
    el("span", { class: "mark__stem" }),
    markLabelEl,
  );

  const intro = el(
    "div",
    { class: "intro", "aria-hidden": "true" },
    el(
      "p",
      { class: "intro__line" },
      el("span", { class: "intro__kicker" }, INTRO.kicker),
      el("span", { class: "intro__name" }, INTRO.name),
    ),
    el("p", { class: "intro__tail" }, INTRO.tail),
  );

  const heroCopy = el(
    "div",
    { class: "page hero__inner" },
    el("p", { class: "eyebrow" }, HERO.eyebrow),
    el("h1", { class: "hero__title" }, HERO.title),
    el("p", { class: "hero__lead" }, HERO.lead),
    el(
      "div",
      { class: "hero__actions" },
      el("a", { class: "btn btn--primary", href: "#ozellikler" }, "Özellikler"),
      el("a", { class: "btn", href: "/hakkimizda" }, "Hakkımızda"),
    ),
  );

  const heroEl = el(
    "section",
    { class: "hero is-intro" },
    heroStageEl,
    intro,
    heroCopy,
    figures(),
  );

  const stepEls = SHOWCASE.map((step, index) =>
    el(
      "li",
      { class: "step", id: index === 0 ? "ozellikler" : step.id },
      el(
        "div",
        { class: "page step__inner" },
        el(
          "p",
          { class: "step__index mono" },
          `${String(index + 1).padStart(2, "0")} / ${String(SHOWCASE.length).padStart(2, "0")}`,
        ),
        el("h2", { class: "step__title" }, step.title),
        el("p", { class: "step__body" }, step.body),
      ),
    ),
  );

  const showcaseEl = el(
    "section",
    { class: "showcase" },
    el("div", { class: "showcase__sticky" }, showcaseStageEl, markEl),
    el("ol", { class: "showcase__steps" }, ...stepEls),
  );

  const moreSection = more();
  const closingSection = closing();

  root.append(header("ana"), heroEl, showcaseEl, moreSection, closingSection, footer());
  heroCopy.inert = true;

  return {
    heroStageEl,
    showcaseEl,
    showcaseStageEl,
    markEl,
    markLabelEl,
    stepEls,
    setPhase(phase) {
      // Giriş sürerken metin odaklanabilir olmamalı: görünmeyen bir bağlantıya
      // sekme ile ulaşmak, ekranda hiçbir şey olmadan odağı kaybettirir.
      heroCopy.inert = phase !== "settled";
      heroEl.classList.toggle("is-intro", phase === "intro");
      heroEl.classList.toggle("is-exiting", phase === "exiting");
      heroEl.classList.toggle("is-settled", phase === "settled");
    },
    revealTargets: [
      ...moreSection.querySelectorAll<HTMLElement>(".feature"),
      closingSection,
    ],
  };
}

function figures(): HTMLElement {
  return el(
    "div",
    { class: "figures" },
    el(
      "dl",
      { class: "page figures__inner" },
      ...FIGURES.map((figure) =>
        el(
          "div",
          { class: "figure" },
          el("dt", { class: "figures__label" }, figure.label),
          el("dd", { class: "figures__value mono" }, figure.value),
        ),
      ),
    ),
  );
}

/** Model üzerinde gösterilmeyen, listede kalan özellikler. */
function more(): HTMLElement {
  return el(
    "section",
    { class: "section", id: "diger" },
    el(
      "div",
      { class: "page" },
      el("div", { class: "section__head" }, el("h2", {}, "Diğer yetenekler")),
      el(
        "div",
        { class: "features" },
        ...FEATURES.map((feature, index) =>
          el(
            "article",
            {
              class: "feature reveal",
              style: `--reveal-delay: ${Math.min(index, 3) * 70}ms`,
            },
            el("h3", { class: "feature__title" }, feature.title),
            el("p", { class: "feature__body" }, feature.body),
          ),
        ),
      ),
    ),
  );
}

function closing(): HTMLElement {
  return el(
    "section",
    { class: "section section--closing reveal" },
    el(
      "div",
      { class: "page closing" },
      el(
        "div",
        {},
        el("h2", {}, CLOSING.title),
        el("p", { class: "section__lead" }, CLOSING.lead),
      ),
      el(
        "a",
        { class: "btn btn--primary", href: SITE.repoUrl, target: "_blank", rel: "noreferrer" },
        CLOSING.action,
      ),
    ),
  );
}
