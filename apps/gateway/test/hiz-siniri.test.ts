import { describe, expect, it } from "vitest";

import { HizSiniri } from "../src/hiz-siniri";

describe("HizSiniri", () => {
  it("limit içinde kabul eder", () => {
    const s = new HizSiniri(3, 1000);
    expect(s.izinVer(0)).toBe(true);
    expect(s.izinVer(1)).toBe(true);
    expect(s.izinVer(2)).toBe(true);
  });

  it("limiti aşınca reddeder", () => {
    const s = new HizSiniri(3, 1000);
    for (let i = 0; i < 3; i++) s.izinVer(i);
    expect(s.izinVer(4)).toBe(false);
  });

  /* Pencere kaydıkça eski damgalar düşer ve yeniden izin verilir. */
  it("pencere kaydıkça yeniden izin verir", () => {
    const s = new HizSiniri(2, 1000);
    expect(s.izinVer(0)).toBe(true);
    expect(s.izinVer(100)).toBe(true);
    expect(s.izinVer(200)).toBe(false);
    expect(s.izinVer(1101)).toBe(true);
  });

  it("reddedilen istek pencereyi doldurmaz", () => {
    const s = new HizSiniri(1, 1000);
    expect(s.izinVer(0)).toBe(true);
    expect(s.izinVer(10)).toBe(false);
    expect(s.izinVer(20)).toBe(false);
    // Pencere yalnızca ilk kabul edilen damgayla dolu; o düşünce açılmalı.
    expect(s.izinVer(1001)).toBe(true);
  });
});
