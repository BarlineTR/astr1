import { beforeAll, describe, expect, it } from "vitest";

import {
  cihazJetonuOzetle,
  cihazJetonuUret,
  panelJetonuCoz,
  panelJetonuImzala,
} from "./cihaz-jeton";

beforeAll(() => {
  process.env.BETTER_AUTH_SECRET ??= "test-sirri-yalnizca-testlerde";
});

describe("cihaz jetonu", () => {
  it("her çağrıda farklı jeton üretir", () => {
    const jetonlar = new Set(Array.from({ length: 100 }, cihazJetonuUret));
    expect(jetonlar.size).toBe(100);
  });

  it("özet jetonun kendisini içermez", () => {
    const jeton = cihazJetonuUret();
    const ozet = cihazJetonuOzetle(jeton);
    expect(ozet).not.toContain(jeton.slice(0, 8));
    expect(ozet).toHaveLength(64);
  });
});

describe("panel jetonu", () => {
  const icerik = {
    cihazId: "cihaz-1",
    kullaniciId: "kullanici-1",
    komutVerebilir: true,
    exp: Date.now() + 60_000,
  };

  it("imzalayıp çözer", () => {
    expect(panelJetonuCoz(panelJetonuImzala(icerik))).toMatchObject({
      cihazId: "cihaz-1",
      komutVerebilir: true,
    });
  });

  /* Gövdesi değiştirilmiş jeton kabul edilmemeli. */
  it("kurcalanmış gövdeyi reddeder", () => {
    const jeton = panelJetonuImzala(icerik);
    const [, imza] = jeton.split(".");
    const sahte = Buffer.from(
      JSON.stringify({ ...icerik, komutVerebilir: true, cihazId: "baska-cihaz" }),
    ).toString("base64url");
    expect(panelJetonuCoz(`${sahte}.${imza}`)).toBeNull();
  });

  it("kurcalanmış imzayı reddeder", () => {
    const [govde] = panelJetonuImzala(icerik).split(".");
    expect(panelJetonuCoz(`${govde}.sahteimza`)).toBeNull();
  });

  it("süresi geçmiş jetonu reddeder", () => {
    const eski = panelJetonuImzala({ ...icerik, exp: Date.now() - 1 });
    expect(panelJetonuCoz(eski)).toBeNull();
  });

  it("biçimsiz jetonu reddeder", () => {
    expect(panelJetonuCoz("")).toBeNull();
    expect(panelJetonuCoz("noktasiz")).toBeNull();
    expect(panelJetonuCoz("a.b.c")).toBeNull();
  });
});
