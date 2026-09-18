/** Küçük DOM yardımcıları. Çerçeve yok; sayfa veri güdümlü ama statik. */

type Child = Node | string | null | undefined | false;

export function el<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  attrs: Record<string, string> = {},
  ...children: Child[]
): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (key === "class") node.className = value;
    else node.setAttribute(key, value);
  }
  append(node, children);
  return node;
}

export function append(parent: Node, children: Child[]): void {
  for (const child of children) {
    if (child === null || child === undefined || child === false) continue;
    parent.appendChild(typeof child === "string" ? document.createTextNode(child) : child);
  }
}

/** Numaralı bölüm iskeleti: solda mono numara, sağda başlık ve giriş. */
export function section(options: {
  id: string;
  index: string;
  title: string;
  lead?: string;
  body: Child[];
}): HTMLElement {
  return el(
    "section",
    { class: "section", id: options.id },
    el(
      "div",
      { class: "page" },
      el(
        "div",
        { class: "section__head" },
        el("div", { class: "section__index" }, options.index),
        el(
          "div",
          {},
          el("h2", {}, options.title),
          options.lead ? el("p", { class: "section__lead" }, options.lead) : null,
        ),
      ),
      el("div", { class: "section__body" }, ...options.body),
    ),
  );
}
