import "../styles/tokens.css";
import "../styles/base.css";
import "../styles/layout.css";

import { renderAbout } from "../pages/about";
import { observeReveals } from "../site/reveal";

const root = document.querySelector<HTMLElement>("#app");
if (!root) throw new Error("#app bulunamadı");

const blocks = renderAbout(root);
observeReveals(blocks, window.matchMedia("(prefers-reduced-motion: reduce)").matches);
