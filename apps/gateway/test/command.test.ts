import { describe, expect, it } from "vitest";

import { HEAD_YAW_LIMIT_DEG } from "@astro/protocol";

import { parseCommand } from "../src/command";

describe("parseCommand", () => {
  it("geçerli komutu çözer", () => {
    expect(parseCommand(JSON.stringify({ kind: "head.center" }))).toEqual({
      ok: true,
      command: { kind: "head.center" },
    });
  });

  it("bozuk JSON'u hata olarak döner, fırlatmaz", () => {
    const sonuc = parseCommand("{bu json değil");
    expect(sonuc.ok).toBe(false);
  });

  /*
   * Sınır ihlali "kırpılarak kabul" edilmez, reddedilir. Sessizce kırpmak
   * operatöre gönderdiği komutun uygulandığını düşündürür.
   */
  it("sınır dışı açıyı reddeder", () => {
    const sonuc = parseCommand(
      JSON.stringify({ kind: "head.target", yawDeg: HEAD_YAW_LIMIT_DEG + 5 }),
    );
    expect(sonuc.ok).toBe(false);
  });

  it("sınırın tam üstündeki açıyı kabul eder", () => {
    const sonuc = parseCommand(
      JSON.stringify({ kind: "head.target", yawDeg: HEAD_YAW_LIMIT_DEG }),
    );
    expect(sonuc.ok).toBe(true);
  });

  it("tanınmayan komutu reddeder", () => {
    expect(parseCommand(JSON.stringify({ kind: "dans.et" })).ok).toBe(false);
  });

  /* Boş gövde de bir komut değildir; JSON.parse onu null olarak çözer. */
  it("boş gövdeyi reddeder", () => {
    expect(parseCommand("null").ok).toBe(false);
  });
});
