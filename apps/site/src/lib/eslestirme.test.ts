import { describe, expect, it } from "vitest";

import { eslestirmeKoduUret, koduOzetle } from "./eslestirme";

describe("eslestirmeKoduUret", () => {
  it("gruplanmış bir kod üretir", () => {
    expect(eslestirmeKoduUret()).toMatch(/^[A-Z2-9]{4}(-[A-Z2-9]{4}){3}$/);
  });

  /*
   * Karışan karakterler alfabede yok: kod elle ya da sesli aktarılacak ve
   * yanlış okunan bir karakter kullanıcıya "geçersiz" demekten başka bir şey
   * söylemiyor.
   */
  it("karışan karakterleri kullanmaz", () => {
    const kod = Array.from({ length: 50 }, eslestirmeKoduUret).join("");
    for (const karisan of ["O", "0", "I", "1", "L"]) {
      expect(kod).not.toContain(karisan);
    }
  });

  it("her çağrıda farklı kod üretir", () => {
    const kodlar = new Set(Array.from({ length: 200 }, eslestirmeKoduUret));
    expect(kodlar.size).toBe(200);
  });
});

describe("koduOzetle", () => {
  it("aynı kod için aynı özeti verir", () => {
    expect(koduOzetle("ABCD-EFGH-JKMN-PQRS")).toBe(koduOzetle("ABCD-EFGH-JKMN-PQRS"));
  });

  it("büyük/küçük harf ve boşluk farkını yok sayar", () => {
    expect(koduOzetle("  abcd-efgh-jkmn-pqrs  ")).toBe(koduOzetle("ABCD-EFGH-JKMN-PQRS"));
  });

  it("farklı kodlar farklı özet verir", () => {
    expect(koduOzetle("ABCD-EFGH-JKMN-PQRS")).not.toBe(koduOzetle("ABCD-EFGH-JKMN-PQRT"));
  });

  it("kodun kendisini geri vermez", () => {
    const kod = "ABCD-EFGH-JKMN-PQRS";
    expect(koduOzetle(kod)).not.toContain("ABCD");
  });
});
