import { describe, expect, it } from "vitest";

import { iletisimSchema } from "./iletisim-sema";

const gecerli = {
  tur: "iletisim" as const,
  ad: "Ada Lovelace",
  eposta: "ada@example.invalid",
  mesaj: "Platform hakkında bilgi almak istiyorum, bir demo mümkün mü?",
  kvkkOnay: true,
};

describe("iletisimSchema", () => {
  it("geçerli formu kabul eder", () => {
    expect(iletisimSchema.parse(gecerli).ad).toBe("Ada Lovelace");
  });

  it("KVKK onayı olmadan reddeder", () => {
    expect(() => iletisimSchema.parse({ ...gecerli, kvkkOnay: false })).toThrow();
  });

  it("bozuk e-postayı reddeder", () => {
    expect(() => iletisimSchema.parse({ ...gecerli, eposta: "ada" })).toThrow();
  });

  it("çok kısa mesajı reddeder", () => {
    expect(() => iletisimSchema.parse({ ...gecerli, mesaj: "selam" })).toThrow();
  });

  /* Teklif talebinde şirket adı zorunlu: kurumsal satış görüşmesi onunla başlar. */
  it("teklif türünde şirket ister", () => {
    expect(() => iletisimSchema.parse({ ...gecerli, tur: "teklif" })).toThrow();
    expect(
      iletisimSchema.parse({ ...gecerli, tur: "teklif", sirket: "Barline" }).sirket,
    ).toBe("Barline");
  });

  it("baş ve sondaki boşlukları kırpar", () => {
    expect(iletisimSchema.parse({ ...gecerli, ad: "  Ada  " }).ad).toBe("Ada");
  });

  /*
   * Tuzak alan: gerçek kullanıcı onu görmez ve doldurmaz. Dolu geldiyse gönderen
   * bir bot demektir. CAPTCHA'sız, JavaScript gerektirmeyen ucuz bir filtre.
   */
  it("tuzak alan doluysa reddeder", () => {
    expect(() => iletisimSchema.parse({ ...gecerli, website: "http://spam" })).toThrow();
  });

  it("çok uzun mesajı reddeder", () => {
    expect(() => iletisimSchema.parse({ ...gecerli, mesaj: "a".repeat(5001) })).toThrow();
  });
});
