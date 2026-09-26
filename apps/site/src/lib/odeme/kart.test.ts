import { describe, expect, it } from "vitest";

import {
  cvcGecerliMi,
  kartAilesi,
  kartNumarasiBicimle,
  luhnGecerliMi,
  sonKullanmaGecerliMi,
} from "./kart";

describe("luhnGecerliMi", () => {
  /* iyzico'nun yayımladığı test kartları — sağlamayı geçmeleri gerekir. */
  it("geçerli test kartlarını kabul eder", () => {
    expect(luhnGecerliMi("5528790000000008")).toBe(true);
    expect(luhnGecerliMi("4766620000000001")).toBe(true);
  });

  it("boşluklu yazımı kabul eder", () => {
    expect(luhnGecerliMi("5528 7900 0000 0008")).toBe(true);
  });

  it("tek hanesi değişmiş numarayı reddeder", () => {
    expect(luhnGecerliMi("5528790000000009")).toBe(false);
  });

  it("çok kısa ve çok uzun numarayı reddeder", () => {
    expect(luhnGecerliMi("4242")).toBe(false);
    expect(luhnGecerliMi("4".repeat(25))).toBe(false);
  });
});

describe("kartNumarasiBicimle", () => {
  it("dörtlü gruplar", () => {
    expect(kartNumarasiBicimle("5528790000000008")).toBe("5528 7900 0000 0008");
  });

  it("rakam olmayanı atar", () => {
    expect(kartNumarasiBicimle("5528-7900abc")).toBe("5528 7900");
  });

  it("on dokuz haneyi aşmaz", () => {
    expect(kartNumarasiBicimle("1".repeat(30)).replace(/\s/g, "")).toHaveLength(19);
  });
});

describe("sonKullanmaGecerliMi", () => {
  const simdi = new Date("2026-09-26T12:00:00Z");

  it("gelecekteki tarihi kabul eder", () => {
    expect(sonKullanmaGecerliMi("12/30", simdi)).toBe(true);
  });

  /* Kart, son kullanma ayının son gününe kadar geçerlidir. */
  it("içinde bulunulan ayı kabul eder", () => {
    expect(sonKullanmaGecerliMi("09/26", simdi)).toBe(true);
  });

  it("geçmiş ayı reddeder", () => {
    expect(sonKullanmaGecerliMi("08/26", simdi)).toBe(false);
  });

  it("geçersiz ayı reddeder", () => {
    expect(sonKullanmaGecerliMi("13/30", simdi)).toBe(false);
    expect(sonKullanmaGecerliMi("00/30", simdi)).toBe(false);
  });

  it("biçimsiz girdiyi reddeder", () => {
    expect(sonKullanmaGecerliMi("1230", simdi)).toBe(false);
    expect(sonKullanmaGecerliMi("", simdi)).toBe(false);
  });
});

describe("cvcGecerliMi", () => {
  it("üç ve dört haneyi kabul eder", () => {
    expect(cvcGecerliMi("123")).toBe(true);
    expect(cvcGecerliMi("1234")).toBe(true);
  });

  it("kısa, uzun ve harfli olanı reddeder", () => {
    expect(cvcGecerliMi("12")).toBe(false);
    expect(cvcGecerliMi("12345")).toBe(false);
    expect(cvcGecerliMi("12a")).toBe(false);
  });
});

describe("kartAilesi", () => {
  it("bilinen aileleri tanır", () => {
    expect(kartAilesi("4766620000000001")).toBe("Visa");
    expect(kartAilesi("5528790000000008")).toBe("Mastercard");
    expect(kartAilesi("9792030000000000")).toBe("Troy");
  });

  it("tanımadığında null döner", () => {
    expect(kartAilesi("1234567890123456")).toBeNull();
  });
});
