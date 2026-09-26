import { describe, expect, it } from "vitest";

import { donusYolu, guvenliDonusYolu, operatorMu, panelYoluMu, yoneticiMi } from "./yetki";

describe("panelYoluMu", () => {
  it("panel yollarını tanır", () => {
    expect(panelYoluMu("/panel")).toBe(true);
    expect(panelYoluMu("/panel/cihaz/abc")).toBe(true);
  });

  it("pazarlama sayfalarını korumaz", () => {
    expect(panelYoluMu("/platform")).toBe(false);
    expect(panelYoluMu("/")).toBe(false);
  });

  /* "/panelist" panel değildir; önek karşılaştırması onu korunan alana sokardı. */
  it("panel ile başlayan başka bir kelimeyi panel saymaz", () => {
    expect(panelYoluMu("/panelist")).toBe(false);
  });
});

describe("guvenliDonusYolu", () => {
  it("iç yolu olduğu gibi döner", () => {
    expect(guvenliDonusYolu("/panel/cihaz/42")).toBe("/panel/cihaz/42");
  });

  it("boş girdide panele döner", () => {
    expect(guvenliDonusYolu(null)).toBe("/panel");
  });

  /* Açık yönlendirme açığı: bizim adresimizde giriş yapıp başka siteye düşmek. */
  it("mutlak dış adresi reddeder", () => {
    expect(guvenliDonusYolu("https://kotu.example/")).toBe("/panel");
  });

  it("protokolsüz çift eğik çizgiyi reddeder", () => {
    expect(guvenliDonusYolu("//kotu.example/")).toBe("/panel");
  });

  it("ters eğik çizgili biçimi reddeder", () => {
    expect(guvenliDonusYolu("/\\kotu.example")).toBe("/panel");
  });
});

describe("donusYolu", () => {
  it("istenen sayfayı kodlayarak taşır", () => {
    expect(donusYolu("/panel/cihaz/42")).toBe("/giris?devam=%2Fpanel%2Fcihaz%2F42");
  });

  it("dış adres istendiğinde panele düşer", () => {
    expect(donusYolu("https://kotu.example/")).toBe("/giris?devam=%2Fpanel");
  });
});

describe("roller", () => {
  it("yönetici yalnızca admin", () => {
    expect(yoneticiMi({ role: "admin" })).toBe(true);
    expect(yoneticiMi({ role: "operator" })).toBe(false);
    expect(yoneticiMi({ role: "customer" })).toBe(false);
  });

  it("operatör yetkisi yöneticiyi de kapsar", () => {
    expect(operatorMu({ role: "admin" })).toBe(true);
    expect(operatorMu({ role: "operator" })).toBe(true);
    expect(operatorMu({ role: "customer" })).toBe(false);
  });
});
