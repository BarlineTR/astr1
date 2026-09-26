import { describe, expect, it } from "vitest";

import { dizgidenKurusa, kurusuDizgiye, sepetToplamiDogrula } from "./tutar";

describe("kurusuDizgiye", () => {
  it("kuruşu ondalık dizgiye çevirir", () => {
    expect(kurusuDizgiye(19990)).toBe("199.90");
  });

  it("tam lirada iki basamak korur", () => {
    expect(kurusuDizgiye(50000)).toBe("500.00");
  });

  it("tek haneli kuruşu sıfırla doldurur", () => {
    expect(kurusuDizgiye(10005)).toBe("100.05");
  });

  it("sıfırı yazabilir", () => {
    expect(kurusuDizgiye(0)).toBe("0.00");
  });

  /* Türkçe yerelde Intl virgül üretir ve istek bozulurdu. */
  it("ondalık ayracı her zaman nokta", () => {
    expect(kurusuDizgiye(149900)).not.toContain(",");
    expect(kurusuDizgiye(149900)).toBe("1499.00");
  });

  it("kayan noktalı girdiyi reddeder", () => {
    expect(() => kurusuDizgiye(199.9)).toThrow(TypeError);
  });

  it("negatif tutarı reddeder", () => {
    expect(() => kurusuDizgiye(-1)).toThrow(RangeError);
  });
});

describe("dizgidenKurusa", () => {
  it("iki basamaklı kesri çözer", () => {
    expect(dizgidenKurusa("199.90")).toBe(19990);
  });

  /* iyzico bazen tek basamak dönüyor: "199.9" ile "199.90" aynı tutar. */
  it("tek basamaklı kesri yüz kuruşa tamamlar", () => {
    expect(dizgidenKurusa("199.9")).toBe(19990);
  });

  it("kesirsiz tutarı çözer", () => {
    expect(dizgidenKurusa("500")).toBe(50000);
  });

  it("boşlukları kırpar", () => {
    expect(dizgidenKurusa("  12.34 ")).toBe(1234);
  });

  it("çözümlenemeyeni reddeder", () => {
    expect(() => dizgidenKurusa("199,90")).toThrow(TypeError);
    expect(() => dizgidenKurusa("abc")).toThrow(TypeError);
  });
});

describe("sepetToplamiDogrula", () => {
  it("toplam eşitse geçer", () => {
    expect(() =>
      sepetToplamiDogrula([{ birimKurus: 5000, adet: 2 }, { birimKurus: 990, adet: 1 }], 10990),
    ).not.toThrow();
  });

  /* Bir kuruşluk fark bile iyzico isteğini tamamen reddettiriyor. */
  it("bir kuruşluk farkı yakalar", () => {
    expect(() => sepetToplamiDogrula([{ birimKurus: 5000, adet: 2 }], 10001)).toThrow(
      RangeError,
    );
  });

  it("boş sepet sıfır olmalı", () => {
    expect(() => sepetToplamiDogrula([], 0)).not.toThrow();
    expect(() => sepetToplamiDogrula([], 100)).toThrow(RangeError);
  });
});
