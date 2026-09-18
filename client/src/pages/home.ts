import { CLOSING, FEATURES, FIGURES, HERO, INTRO, SITE } from "../data/content";
import { el } from "../dom";
import { footer, header } from "../site/chrome";

export interface HomeView {
  stageEl: HTMLElement;
  heroEl: HTMLElement;
  /** Açılış animasyonunu bir sonraki evreye geçirir. */
  setPhase(phase: "intro" | "settled"): void;
  /** Kaydırmayla ortaya çıkan parçaları izlemeye alır. */
  revealTargets: HTMLElement[];
}

export function renderHome(root: HTMLElement): HomeView {
  const stageEl = el("div", { class: "hero__stage", id: "stage" });

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
    el("p", { class: "eyebrow hero__eyebrow" }, HERO.eyebrow),
    el("h1", { class: "hero__title" }, HERO.title),
    el("p", { class: "hero__lead" }, HERO.lead),
    el(
      "div",
      { class: "hero__actions" },
      el("a", { class: "btn btn--primary", href: "#ozellikler" }, "Özellikler"),
      el("a", { class: "btn", href: "/hakkimizda" }, "Hakkımızda"),
    ),
  );

  const figuresEl = el(
    "div",
    { class: "figures" },
    el(
      "dl",
      { class: "page figures__inner" },
      // Her çift kendi kutusunda: ızgara akışına bırakılınca etiket ve değer
      // dar ekranda ayrı sütunlara düşüp birbirinden kopuyordu.
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

  const heroEl = el("section", { class: "hero is-intro" }, stageEl, intro, heroCopy, figuresEl);

  const featuresSection = features();
  const closingSection = closing();

  root.append(header("ana"), heroEl, featuresSection, closingSection, footer());

  return {
    stageEl,
    heroEl,
    setPhase(phase) {
      heroEl.classList.toggle("is-intro", phase === "intro");
      heroEl.classList.toggle("is-settled", phase === "settled");
    },
    revealTargets: [
      ...featuresSection.querySelectorAll<HTMLElement>(".feature"),
      closingSection,
    ],
  };
}

function features(): HTMLElement {
  return el(
    "section",
    { class: "section", id: "ozellikler" },
    el(
      "div",
      { class: "page" },
      el(
        "div",
        { class: "section__head" },
        el("h2", {}, "Özellikler"),
        el("p", { class: "section__lead" }, "ASTRO'nun sahada kullanılan yetenekleri."),
      ),
      el(
        "div",
        { class: "features" },
        ...FEATURES.map((feature, index) =>
          el(
            "article",
            {
              class: "feature reveal",
              // Sıralı gecikme: kartlar aynı anda değil, birbiri ardına belirir.
              style: `--reveal-delay: ${Math.min(index, 3) * 70}ms`,
            },
            el("span", { class: "feature__index mono" }, String(index + 1).padStart(2, "0")),
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
