import { ABOUT, SITE } from "../data/content";
import { el } from "../dom";
import { footer, header } from "../site/chrome";

/**
 * Hakkımızda.
 *
 * Metin taslaktır ve `content.ts` içindeki `ABOUT` sabitinden gelir. Kuruluş yılı,
 * çalışan sayısı, müşteri ya da ödül gibi doğrulanabilir iddialar bilerek
 * yazılmamıştır — gerçek bilgiler gelene kadar yanlış bir şey iddia etmemek için.
 */
export function renderAbout(root: HTMLElement): HTMLElement[] {
  const blocks = ABOUT.sections.map((section) =>
    el(
      "section",
      { class: "section", id: section.id },
      el(
        "div",
        { class: "page prose reveal" },
        el(
          "div",
          { class: "section__head" },
          el("h2", {}, section.title),
        ),
        ..."paragraphs" in section
          ? section.paragraphs.map((text) => el("p", { class: "prose__p" }, text))
          : [
              el(
                "ul",
                { class: "prose__list" },
                ...section.items.map((item) => el("li", {}, item)),
              ),
            ],
      ),
    ),
  );

  const contact = el(
    "section",
    { class: "section section--closing", id: "iletisim" },
    el(
      "div",
      { class: "page closing reveal" },
      el(
        "div",
        {},
        el("h2", {}, ABOUT.contact.title),
        el("p", { class: "section__lead" }, ABOUT.contact.body),
      ),
      el(
        "a",
        { class: "btn btn--primary", href: SITE.repoUrl, target: "_blank", rel: "noreferrer" },
        "Depoyu görüntüle",
      ),
    ),
  );

  const intro = el(
    "section",
    { class: "section section--flush" },
    el(
      "div",
      { class: "page" },
      el("p", { class: "eyebrow reveal" }, "Kurumsal"),
      el("h1", { class: "page-title reveal", style: "--reveal-delay: 80ms" }, "Hakkımızda"),
      el("p", { class: "section__lead page-lead reveal", style: "--reveal-delay: 160ms" }, ABOUT.lead),
    ),
  );
  const main = el("main", { class: "about" }, intro, ...blocks, contact);

  root.append(
    header("hakkimizda"),
    main,
    footer(),
  );

  return [...main.querySelectorAll<HTMLElement>(".reveal")];
}
