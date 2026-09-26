import { describe, expect, it } from "vitest";

import { kurusBicimle, sayiBicimle } from "./para";

describe("kurusBicimle", () => {
  it("kuruşu Türk lirası olarak yazar", () => {
    expect(kurusBicimle(19990)).toBe("₺199,90");
  });

  it("tam liraya kuruş basamağı ekler", () => {
    expect(kurusBicimle(50000)).toBe("₺500,00");
  });

  it("binlik ayracı koyar", () => {
    expect(kurusBicimle(149900)).toBe("₺1.499,00");
  });

  /*
   * Kayan noktalı bir tutar buraya kadar geldiyse yukarıda bir yerde para
   * bozulmuş demektir; sessizce yuvarlamak o hatayı gizler.
   */
  it("tam sayı olmayan girdiyi reddeder", () => {
    expect(() => kurusBicimle(199.9)).toThrow(TypeError);
  });
});

describe("sayiBicimle", () => {
  it("ondalık ayracı virgül kullanır", () => {
    expect(sayiBicimle(2.5882, 4)).toBe("2,5882");
  });

  it("basamak sayısını sabitler", () => {
    expect(sayiBicimle(1.159)).toBe("1,16");
  });

  it("tam sayıyı basamaksız verebilir", () => {
    expect(sayiBicimle(36, 0)).toBe("36");
  });
});
