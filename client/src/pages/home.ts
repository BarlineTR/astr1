import { CLOSING, FEATURES, FIGURES, HERO, INTRO, SHOWCASE, SITE } from "../data/content";
import { el } from "../dom";
import { footer, header } from "../site/chrome";

/**
 * Açılışın üç evresi.
 *
 * `exiting` ayrı bir evre, çünkü isim ile metnin geçişleri aynı anda başlayınca
 * üst üste biniyordu: "ASTRO" daha silinmeden başlık soldan giriyordu. Şimdi
 * isim önce tamamen çekiliyor, metin ondan sonra geliyor.
 */
export type IntroPhase = "intro" | "exiting" | "settled";

export interface HomeView {
  stageEl: HTMLElement;
  markEl: HTMLElement;
  markLabelEl: HTMLElement;
  stepEls: HTMLElement[];
  setPhase(phase: IntroPhase): void;
  revealTargets: HTMLElement[];
}

/**
 * Ana sayfa.
 *
 * Sayfanın ilk bölümü tek bir "film"dir: 3B sahne yapışkan olarak ekranda sabit
 * durur, metin ekranları onun üzerinden akar. Önce giriş, sonra özelliklerin
 * model üzerinde tek tek gösterildiği adımlar. Tek bir tuval kullanılır —
 * ikinci bir sahne, modeli ve dokularını ikinci kez ekran kartına yüklerdi.
 */
export function renderHome(root: HTMLElement): HomeView {
  const stageEl = el("div", { class: "film__stage", id: "stage" });

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

  const heroScreen = el(
    "section",
    { class: "screen screen--hero" },
    el(
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
    ),
    figures(),
  );

  const stepEls = SHOWCASE.map((step, index) =>
    el(
      "li",
      { class: "screen step", id: index === 0 ? "ozellikler" : step.id },
      el(
        "div",
        { class: "page step__inner" },
        el("p", { class: "step__index mono" }, `${String(index + 1).padStart(2, "0")} / ${String(SHOWCASE.length).padStart(2, "0")}`),
        el("h2", { class: "step__title" }, step.title),
        el("p", { class: "step__body" }, step.body),
      ),
    ),
  );

  const film = el(
    "div",
    { class: "film is-intro" },
    el("div", { class: "film__sticky" }, stageEl, markEl, intro),
    el(
      "div",
      { class: "film__screens" },
      heroScreen,
      el("ol", { class: "film__steps" }, ...stepEls),
    ),
  );

  const moreSection = more();
  const closingSection = closing();

  root.append(header("ana"), film, moreSection, closingSection, footer());

  return {
    stageEl,
    markEl,
    markLabelEl,
    stepEls,
    setPhase(phase) {
      film.classList.toggle("is-intro", phase === "intro");
      film.classList.toggle("is-exiting", phase === "exiting");
      film.classList.toggle("is-settled", phase === "settled");
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
      el(
        "div",
        { class: "section__head" },
        el("h2", {}, "Diğer yetenekler"),
      ),
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
