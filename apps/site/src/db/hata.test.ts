import { describe, expect, it } from "vitest";

import { tekilIhlalMi } from "./hata";

/** Drizzle hatayı sarıyor; gerçek hata `cause` zincirinde kalıyor. */
function sarmalanmisHata(code: string, constraint?: string) {
  const pg = Object.assign(new Error("duplicate key value"), { code, constraint });
  return Object.assign(new Error("Failed query: insert into devices ..."), { cause: pg });
}

describe("tekilIhlalMi", () => {
  it("sarmalanmış tekil ihlali tanır", () => {
    expect(tekilIhlalMi(sarmalanmisHata("23505", "devices_serial_unique"))).toBe(true);
  });

  it("kısıt adı verildiğinde yalnızca o kısıtta doğrudur", () => {
    const hata = sarmalanmisHata("23505", "devices_serial_unique");
    expect(tekilIhlalMi(hata, "devices_serial_unique")).toBe(true);
    expect(tekilIhlalMi(hata, "users_email_unique")).toBe(false);
  });

  it("başka bir hata kodunu tekil ihlal saymaz", () => {
    expect(tekilIhlalMi(sarmalanmisHata("23503", "devices_owner_fk"))).toBe(false);
  });

  it("sıradan hatada yanılmaz", () => {
    expect(tekilIhlalMi(new Error("bir şey oldu"))).toBe(false);
    expect(tekilIhlalMi(null)).toBe(false);
    expect(tekilIhlalMi("metin")).toBe(false);
  });

  /* Döngüsel cause zinciri sonsuz özyinelemeye girmemeli. */
  it("derin zincirde durur", () => {
    const a: { cause?: unknown } = {};
    a.cause = a;
    expect(tekilIhlalMi(a)).toBe(false);
  });
});
