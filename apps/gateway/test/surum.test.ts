import { describe, expect, it } from "vitest";

import { PROTOCOL_VERSION } from "@astro/protocol";

import { surumUyumlu } from "../src/surum";

describe("surumUyumlu", () => {
  it("aynı sürümü kabul eder", () => {
    expect(surumUyumlu(PROTOCOL_VERSION)).toBe(true);
  });

  it("aynı ana sürümün alt sürümünü kabul eder", () => {
    expect(surumUyumlu(`${PROTOCOL_VERSION}.7`)).toBe(true);
  });

  it("farklı ana sürümü reddeder", () => {
    expect(surumUyumlu("99")).toBe(false);
  });

  it("boş sürümü reddeder", () => {
    expect(surumUyumlu("")).toBe(false);
  });
});
