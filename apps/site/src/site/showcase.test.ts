import { afterEach, expect, it, vi } from "vitest";
import { startShowcase } from "./showcase";
import type { RobotScene, FocusTarget } from "../scene/robot-scene";

function setup(compact = true, initialStep = -1) {
  const screenHeight = compact ? 844 : 900;
  let scrollY = initialStep < 0 ? 0 : 900 + initialStep * screenHeight;
  let resized = () => {};
  const media = Object.assign(new EventTarget(), { matches: compact });
  const win = Object.assign(new EventTarget(), { innerHeight: screenHeight, matchMedia: () => media });
  vi.stubGlobal("window", win);
  vi.stubGlobal("document", { querySelector: () => ({ getBoundingClientRect: () => ({ bottom: 60 }) }) });
  vi.stubGlobal("ResizeObserver", class {
    constructor(callback: () => void) { resized = callback; }
    observe() {}
    disconnect() {}
  });
  let frameId = 0;
  const frames = new Map<number, FrameRequestCallback>();
  vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => {
    frames.set(++frameId, callback);
    return frameId;
  });
  vi.stubGlobal("cancelAnimationFrame", (id: number) => frames.delete(id));
  const flush = () => {
    const callbacks = [...frames.values()];
    frames.clear();
    callbacks.forEach(callback => callback(0));
  };
  const element = () => {
    const classes = new Set<string>();
    return {
      classList: {
        add: (...names: string[]) => names.forEach(name => classes.add(name)),
        remove: (...names: string[]) => names.forEach(name => classes.delete(name)),
        toggle(name: string, force: boolean) { if (force) classes.add(name); else classes.delete(name); },
        contains: (name: string) => classes.has(name),
      },
      textContent: "",
    };
  };
  const contents = Array.from({ length: 6 }, () => ({ offsetTop: compact ? 600 : 350, offsetHeight: 196 }));
  const steps = contents.map((content, i) => Object.assign(element(), {
    querySelector: () => content,
    getBoundingClientRect: () => ({ top: 900 + i * screenHeight - scrollY, bottom: 900 + (i + 1) * screenHeight - scrollY }),
  }));
  const mark = element();
  const label = element();
  const focus = vi.fn<(target: FocusTarget | null) => void>();
  const scene = { metrics: { height: 1, radius: 0.3 }, focus, onFrame() {} } as unknown as RobotScene;
  const controller = startShowcase({
    scene, steps: steps as unknown as HTMLElement[], markEl: mark as unknown as HTMLElement,
    markLabelEl: label as unknown as HTMLElement, stageEl: element() as unknown as HTMLElement,
  });
  return {
    focus, controller, media, win, mark, label, contents, flush,
    active: () => steps.findIndex(step => step.classList.contains("is-active")),
    scroll(index: number, screenTop = 0, render = true) {
      scrollY = 900 + index * screenHeight - screenTop;
      win.dispatchEvent(new Event("scroll"));
      if (render) flush();
    },
    resize() { resized(); flush(); },
  };
}

it.each([true, false])("does not activate Social Gaze before its copy reaches the reading area (mobile: %s)", compact => {
  const s = setup(compact);
  s.scroll(1);
  s.scroll(2, compact ? 364 : 390);
  expect(s.active()).toBe(1);
  expect(s.label.textContent).toBe("Mikrofon dizisi");
  s.scroll(2);
  expect(s.active()).toBe(2);
  expect(s.label.textContent).toBe("Kafa ekseni");
  s.controller.stop();
});

it("chooses the same step for the same position in both scroll directions", () => {
  const s = setup();
  s.scroll(2, 100);
  expect(s.active()).toBe(1);
  s.scroll(4);
  s.scroll(2, 100);
  expect(s.active()).toBe(1);
  s.controller.stop();
});

it("applies only the final destination of a fast jump, without an overview or intermediate focus", () => {
  const s = setup();
  s.scroll(0);
  s.focus.mockClear();
  s.scroll(1, 0, false);
  s.scroll(3, 0, false);
  s.scroll(5, 0, false);
  s.flush();
  expect(s.active()).toBe(5);
  expect(s.focus).toHaveBeenCalledTimes(1);
  expect(s.focus.mock.calls[0]![0]).not.toBeNull();
  s.controller.stop();
});

it("joins an already-scrolled page immediately when the model finishes loading", () => {
  const s = setup(true, 2);
  expect(s.active()).toBe(2);
  expect(s.label.textContent).toBe("Kafa ekseni");
  s.controller.stop();
});

it("hides the previous label in the gap while preserving its camera until the next copy arrives", () => {
  const s = setup();
  s.scroll(1);
  expect(s.mark.classList.contains("is-visible")).toBe(true);
  s.focus.mockClear();
  s.scroll(2, 100);
  expect(s.active()).toBe(1);
  expect(s.mark.classList.contains("is-visible")).toBe(false);
  expect(s.focus).not.toHaveBeenCalled();
  s.scroll(2);
  expect(s.mark.classList.contains("is-visible")).toBe(true);
  s.controller.stop();
});

it("leaves the tour at both ends and clears the marker", () => {
  const s = setup();
  s.scroll(0);
  s.scroll(0, 900);
  expect(s.active()).toBe(-1);
  expect(s.focus).toHaveBeenLastCalledWith(null);
  s.scroll(5);
  s.scroll(5, -844);
  expect(s.active()).toBe(-1);
  expect(s.mark.classList.contains("is-visible")).toBe(false);
  s.controller.stop();
});

it("recalculates after text reflow even when the enclosing screen size stays unchanged", () => {
  const s = setup();
  s.scroll(2, 100);
  expect(s.active()).toBe(1);
  s.contents[2]!.offsetTop = 400;
  s.resize();
  expect(s.active()).toBe(2);
  s.controller.stop();
});

it("keeps the mobile robot's scale and height consistent across all six steps", () => {
  const s = setup();
  for (let i = 0; i < 6; i++) s.scroll(i);
  const targets = s.focus.mock.calls.map(([target]) => target!);
  for (const target of targets) {
    expect(target.point.toArray()).toEqual(targets[0]!.point.toArray());
    expect(target.distance).toBe(targets[0]!.distance);
    expect(target.polarDeg).toBe(targets[0]!.polarDeg);
  }
  expect(Math.max(...targets.map(t => t.azimuthDeg)) - Math.min(...targets.map(t => t.azimuthDeg))).toBeLessThan(12);
  s.controller.stop();
});

it("reframes on breakpoint change and cancels pending work when stopped", () => {
  const s = setup(true, 5);
  const compact = s.focus.mock.calls.at(-1)![0]!;
  s.media.matches = false;
  s.contents[5]!.offsetTop = 350;
  s.media.dispatchEvent(new Event("change"));
  s.flush();
  const desktop = s.focus.mock.calls.at(-1)![0]!;
  expect(desktop.point.y).toBeLessThan(compact.point.y);
  expect(desktop.distance).toBeLessThan(compact.distance);
  s.scroll(4, 0, false);
  s.controller.stop();
  s.focus.mockClear();
  s.flush();
  s.win.dispatchEvent(new Event("resize"));
  s.media.dispatchEvent(new Event("change"));
  s.resize();
  expect(s.focus).not.toHaveBeenCalled();
});

afterEach(() => vi.unstubAllGlobals());
