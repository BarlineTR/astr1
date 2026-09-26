import { describe, expect, it } from "vitest";

import { sahteSaglayici } from "./sahte";
import type { SahteSaglayiciEk } from "./sahte";
import type { OdemeBaslatGirdi } from "./saglayici";

const GIRDI: OdemeBaslatGirdi = {
  siparisId: "siparis-1",
  conversationId: "astro-siparis-1",
  toplamKurus: 15000,
  paraBirimi: "TRY",
  kalemler: [{ slug: "kahve", ad: "Kahve", birimKurus: 15000, adet: 1 }],
  alici: {
    id: "k1",
    ad: "Ada",
    soyad: "Lovelace",
    eposta: "ada@example.invalid",
    ip: "127.0.0.1",
  },
  geriDonusUrl: "http://localhost:3000/api/odeme/geri-donus",
};

function kur() {
  const s = sahteSaglayici("http://localhost:3000");
  return { s, ek: s as unknown as SahteSaglayiciEk };
}

describe("sahte sağlayıcı", () => {
  it("canlı değil olarak işaretli", () => {
    expect(kur().s.canli).toBe(false);
  });

  it("ödeme sayfasına yönlendirir", async () => {
    const { s } = kur();
    const sonuc = await s.odemeBaslat(GIRDI);
    expect(sonuc.ok).toBe(true);
    expect(sonuc.odemeSayfasiUrl).toContain("/odeme/sahte/");
    expect(sonuc.token).toMatch(/^sahte_/);
  });

  /*
   * Gerçek sağlayıcıyla aynı doğrulamaları yapmalı; sahtede geçip gerçekte
   * patlayan bir hata en kötüsü.
   */
  it("sepet toplamı uyuşmazsa reddeder", async () => {
    const { s } = kur();
    await expect(
      s.odemeBaslat({ ...GIRDI, toplamKurus: 14999 }),
    ).rejects.toThrow(RangeError);
  });

  it("karar verilmemiş ödeme başarısız sayılır", async () => {
    const { s } = kur();
    const baslat = await s.odemeBaslat(GIRDI);
    const sonuc = await s.sonucuAl(baslat.token!);
    expect(sonuc.durum).toBe("basarisiz");
  });

  it("onaylanan ödeme başarılı döner", async () => {
    const { s, ek } = kur();
    const baslat = await s.odemeBaslat(GIRDI);
    ek.sahteKararVer(baslat.token!, "basarili");

    const sonuc = await s.sonucuAl(baslat.token!);
    expect(sonuc.durum).toBe("basarili");
    expect(sonuc.tutarKurus).toBe(15000);
    expect(sonuc.conversationId).toBe("astro-siparis-1");
  });

  /* İdempotensi ödeme kimliğinin sabit olmasına dayanıyor. */
  it("aynı oturum için ödeme kimliği sabit", async () => {
    const { s, ek } = kur();
    const baslat = await s.odemeBaslat(GIRDI);
    ek.sahteKararVer(baslat.token!, "basarili");

    const a = await s.sonucuAl(baslat.token!);
    const b = await s.sonucuAl(baslat.token!);
    expect(a.odemeId).toBe(b.odemeId);
  });

  it("bilinmeyen oturumu tanımaz", async () => {
    const { s, ek } = kur();
    expect(ek.sahteOturumVarMi("yok")).toBe(false);
    expect((await s.sonucuAl("yok")).durum).toBe("bilinmiyor");
  });
});
