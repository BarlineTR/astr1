import { CONSOLE_INTRO } from "../data/content";
import { HEAD_YAW_LIMIT_DEG } from "../../../shared/limits";
import type { Command, Telemetry } from "../../../shared/protocol";
import { el } from "../dom";
import { footer, header } from "../site/chrome";

export interface ConsoleView {
  stageEl: HTMLElement;
  /** Gelen telemetriyi ekrana yazar. */
  update(telemetry: Telemetry): void;
  /** Kaynak kurulunca çağrılır; komut göndericisini bağlar. */
  bind(send: (command: Command) => void, kind: "websocket" | "browser"): void;
}

export function renderConsole(root: HTMLElement): ConsoleView {
  const stageEl = el("div", { class: "console__stage", id: "stage" });

  const badge = el("span", { class: "badge" }, "bağlanıyor…");
  const notice = el(
    "p",
    { class: "console__notice" },
    "Telemetri kaynağı belirleniyor.",
  );

  const readouts = {
    desired: value("İstenen açı", "—"),
    actual: value("Ölçülen açı", "—"),
    owner: value("Dikkat", "—"),
    state: value("Durum", "—"),
    doa: value("Ses yönü", "—"),
    faces: value("Görülen yüz", "—"),
  };

  const gauge = createGauge();
  const compass = createCompass();

  const slider = el("input", {
    type: "range",
    class: "slider",
    min: String(-HEAD_YAW_LIMIT_DEG),
    max: String(HEAD_YAW_LIMIT_DEG),
    step: "1",
    value: "0",
    "aria-label": "Kafa hedef açısı",
  }) as HTMLInputElement;
  const sliderValue = el("span", { class: "slider__value mono" }, "0°");

  const centerButton = el("button", { class: "btn", type: "button" }, "Merkeze al");
  const stopButton = el("button", { class: "btn btn--alarm", type: "button" }, "ACİL DURDURMA");

  let send: ((command: Command) => void) | null = null;
  let eStop = false;

  slider.addEventListener("input", () => {
    const yaw = Number(slider.value);
    sliderValue.textContent = `${yaw}°`;
    send?.({ kind: "head.target", yawDeg: yaw });
  });

  centerButton.addEventListener("click", () => {
    slider.value = "0";
    sliderValue.textContent = "0°";
    send?.({ kind: "head.center" });
  });

  stopButton.addEventListener("click", () => {
    eStop = !eStop;
    stopButton.textContent = eStop ? "DURDURMAYI KALDIR" : "ACİL DURDURMA";
    stopButton.classList.toggle("is-engaged", eStop);
    send?.({ kind: "estop", engaged: eStop });
  });

  root.append(
    header("konsol"),
    el(
      "section",
      { class: "section section--flush console" },
      el(
        "div",
        { class: "page" },
        el(
          "div",
          { class: "console__head" },
          el(
            "div",
            {},
            el("p", { class: "eyebrow" }, "Kontrol"),
            el("h1", { class: "page-title" }, CONSOLE_INTRO.title),
            el("p", { class: "section__lead" }, CONSOLE_INTRO.lead),
          ),
          badge,
        ),
        notice,
        el(
          "div",
          { class: "console__grid" },
          el("div", { class: "panel panel--stage" }, stageEl),
          el(
            "div",
            { class: "panel" },
            el("p", { class: "panel__title" }, "Durum"),
            el("dl", { class: "readouts" }, ...Object.values(readouts).map((r) => r.node)),
          ),
          el(
            "div",
            { class: "panel" },
            el("p", { class: "panel__title" }, "Kafa açısı"),
            gauge.node,
          ),
          el(
            "div",
            { class: "panel" },
            el("p", { class: "panel__title" }, "Ses yönü"),
            compass.node,
          ),
          el(
            "div",
            { class: "panel panel--wide" },
            el("p", { class: "panel__title" }, "Komut"),
            el(
              "div",
              { class: "controls" },
              el("div", { class: "controls__slider" }, slider, sliderValue),
              el("div", { class: "controls__buttons" }, centerButton, stopButton),
            ),
            el(
              "p",
              { class: "controls__note" },
              `Hedef açı ±${HEAD_YAW_LIMIT_DEG}° aralığına kaynakta kırpılır. ` +
                "Arayüzdeki sınır yalnızca geri bildirimdir.",
            ),
          ),
        ),
      ),
    ),
    footer(),
  );

  return {
    stageEl,
    bind(sender, kind) {
      send = sender;
      if (kind === "websocket") {
        badge.textContent = "sunucuya bağlı";
        badge.className = "badge badge--live";
        notice.textContent =
          "Sunucuya bağlanıldı. Veri kaynağı her pakette belirtilir.";
      } else {
        badge.textContent = "simülasyon";
        badge.className = "badge badge--mock";
        notice.textContent =
          "Sunucu bulunamadı; senaryo tarayıcıda çalışıyor. Buradaki hiçbir değer " +
          "gerçek bir robottan gelmiyor.";
      }
    },
    update(telemetry) {
      readouts.desired.set(`${telemetry.head.desiredYawDeg.toFixed(1)}°`);
      readouts.actual.set(
        telemetry.head.encoderOk ? `${telemetry.head.actualYawDeg.toFixed(1)}°` : "geri besleme yok",
      );
      readouts.owner.set(OWNER_LABEL[telemetry.gaze.attentionOwner]);
      readouts.state.set(telemetry.gaze.state);
      readouts.doa.set(
        telemetry.audio.doaDeg === null
          ? "—"
          : `${telemetry.audio.doaDeg.toFixed(0)}° · güven ${telemetry.audio.confidence.toFixed(2)}`,
      );
      readouts.faces.set(String(telemetry.faces.length));

      gauge.set(telemetry.head.desiredYawDeg, telemetry.head.actualYawDeg);
      compass.set(telemetry.audio.doaDeg, telemetry.audio.vad);

      if (telemetry.safety.eStop !== eStop) {
        eStop = telemetry.safety.eStop;
        stopButton.textContent = eStop ? "DURDURMAYI KALDIR" : "ACİL DURDURMA";
        stopButton.classList.toggle("is-engaged", eStop);
      }
    },
  };
}

const OWNER_LABEL = {
  visual: "görüntü",
  audio: "ses",
  none: "yok",
} as const;

function value(label: string, initial: string): { node: DocumentFragment; set(v: string): void } {
  const dd = el("dd", { class: "readouts__value mono" }, initial);
  const fragment = document.createDocumentFragment();
  fragment.append(el("dt", { class: "readouts__label" }, label), dd);
  return {
    node: fragment,
    set(next: string) {
      dd.textContent = next;
    },
  };
}

/** İstenen ve ölçülen açıyı aynı yay üzerinde iki iğne olarak gösterir. */
function createGauge(): { node: SVGSVGElement; set(desired: number, actual: number): void } {
  const svg = svgEl("svg", { viewBox: "0 0 200 116", class: "gauge" });
  const arc = svgEl("path", {
    d: describeArc(100, 100, 82, -HEAD_YAW_LIMIT_DEG, HEAD_YAW_LIMIT_DEG),
    class: "gauge__arc",
  });
  const desiredNeedle = svgEl("line", { class: "gauge__needle gauge__needle--desired" });
  const actualNeedle = svgEl("line", { class: "gauge__needle gauge__needle--actual" });
  svg.append(arc, desiredNeedle, actualNeedle);

  const place = (needle: SVGElement, deg: number, length: number): void => {
    const rad = ((deg - 90) * Math.PI) / 180;
    needle.setAttribute("x1", "100");
    needle.setAttribute("y1", "100");
    needle.setAttribute("x2", String(100 + Math.cos(rad) * length));
    needle.setAttribute("y2", String(100 + Math.sin(rad) * length));
  };

  return {
    node: svg,
    set(desired, actual) {
      place(desiredNeedle, desired, 76);
      place(actualNeedle, actual, 62);
    },
  };
}

/** Gövde çerçevesinde ses yönü pusulası. */
function createCompass(): { node: SVGSVGElement; set(deg: number | null, vad: boolean): void } {
  const svg = svgEl("svg", { viewBox: "0 0 160 160", class: "compass" });
  const ring = svgEl("circle", { cx: "80", cy: "80", r: "62", class: "compass__ring" });
  const front = svgEl("line", { x1: "80", y1: "18", x2: "80", y2: "30", class: "compass__front" });
  const marker = svgEl("circle", { r: "7", class: "compass__marker" });
  marker.setAttribute("opacity", "0");
  svg.append(ring, front, marker);

  return {
    node: svg,
    set(deg, vad) {
      if (deg === null) {
        marker.setAttribute("opacity", "0");
        return;
      }
      const rad = ((deg - 90) * Math.PI) / 180;
      marker.setAttribute("cx", String(80 + Math.cos(rad) * 62));
      marker.setAttribute("cy", String(80 + Math.sin(rad) * 62));
      marker.setAttribute("opacity", vad ? "1" : "0.35");
    },
  };
}

function svgEl<K extends keyof SVGElementTagNameMap>(
  tag: K,
  attrs: Record<string, string> = {},
): SVGElementTagNameMap[K] {
  const node = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [key, val] of Object.entries(attrs)) node.setAttribute(key, val);
  return node;
}

function describeArc(cx: number, cy: number, r: number, from: number, to: number): string {
  const point = (deg: number): [number, number] => {
    const rad = ((deg - 90) * Math.PI) / 180;
    return [cx + Math.cos(rad) * r, cy + Math.sin(rad) * r];
  };
  const [x1, y1] = point(from);
  const [x2, y2] = point(to);
  const large = Math.abs(to - from) > 180 ? 1 : 0;
  return `M ${x1} ${y1} A ${r} ${r} 0 ${large} 1 ${x2} ${y2}`;
}
