import { SITE } from "../data/content";
import { el } from "../dom";

export type PageId = "ana" | "hakkimizda" | "konsol";

const NAV: Array<{ id: PageId; label: string; href: string }> = [
  { id: "ana", label: "Ana sayfa", href: "/" },
  { id: "hakkimizda", label: "Hakkımızda", href: "/hakkimizda" },
];

/** Konsol gezinme bağlantısı değil, eylem. Şeritte çerçeveli ve bir tık büyük durur. */
const CONSOLE_LINK = { id: "konsol" as const, label: "Konsol", href: "/konsol" };

/** Üç sayfanın paylaştığı başlık şeridi. Etkin sayfa işaretlenir. */
export function header(current: PageId): HTMLElement {
  return el(
    "header",
    { class: "site-header" },
    el(
      "div",
      { class: "page site-header__inner" },
      el(
        "a",
        { class: "site-header__mark", href: "/" },
        SITE.name,
        el("span", {}, SITE.version),
      ),
      el(
        "nav",
        { class: "site-nav", "aria-label": "Sayfalar" },
        ...NAV.map((item) =>
          el(
            "a",
            item.id === current
              ? { href: item.href, class: "is-current", "aria-current": "page" }
              : { href: item.href },
            item.label,
          ),
        ),
      ),
      el(
        "a",
        { class: "btn btn--quiet", href: SITE.repoUrl, target: "_blank", rel: "noreferrer" },
        "Depo",
      ),
      el(
        "a",
        current === CONSOLE_LINK.id
          ? { class: "btn btn--console is-current", href: CONSOLE_LINK.href, "aria-current": "page" }
          : { class: "btn btn--console", href: CONSOLE_LINK.href },
        CONSOLE_LINK.label,
      ),
    ),
  );
}

export function footer(): HTMLElement {
  const year = new Date().getFullYear();
  return el(
    "footer",
    { class: "site-footer" },
    el(
      "div",
      { class: "page site-footer__inner" },
      el("p", {}, `© ${year} ${SITE.name} ${SITE.version}`),
      el(
        "nav",
        { class: "site-footer__nav", "aria-label": "Alt bağlantılar" },
        ...NAV.map((item) => el("a", { href: item.href }, item.label)),
        el("a", { href: CONSOLE_LINK.href }, CONSOLE_LINK.label),
        el("a", { href: SITE.repoUrl, target: "_blank", rel: "noreferrer" }, "Kaynak kod"),
      ),
    ),
  );
}
