import { describe, expect, it } from "vitest";

import { sahteAbonelik } from "./sahte-abonelik";
import type { AbonelikBaslatGirdi } from "./saglayici";

const GIRDI: AbonelikBaslatGirdi = {
  abonelikId: "ab-1",
  conversationId: "astro-ab-1",
  planRef: "gozlem",
  planAdi: "Gözlem",
  fiyatKurus: 49900,
  alici: {
    id: "k1",
    ad: "Ada",
    soyad: "Lovelace",
    eposta: "ada@example.invalid",
    ip: "127.0.0.1",
  },
  geriDonusUrl: "http://localhost:3000/api/odeme/abonelik-geri-donus",
};

async function aktifAbonelikKur() {
  const s = sahteAbonelik("http://localhost:3000");
  const baslat = await s.abonelikBaslat(GIRDI);
  s.sahteAbonelikKarar(baslat.token!, "basarili");
  const sonuc = await s.abonelikSonucuAl(baslat.token!);
  return { s, token: baslat.token!, ref: sonuc.abonelikRef! };
}

describe("sahte abonelik", () => {
  it("ödeme sayfasına yönlendirir", async () => {
    const s = sahteAbonelik("http://localhost:3000");
    const baslat = await s.abonelikBaslat(GIRDI);
    expect(baslat.ok).toBe(true);
    expect(baslat.odemeSayfasiUrl).toContain("/odeme/sahte-abonelik/");
  });

  it("karar verilmeden bekliyor durumunda", async () => {
    const s = sahteAbonelik("http://localhost:3000");
    const baslat = await s.abonelikBaslat(GIRDI);
    expect((await s.abonelikSonucuAl(baslat.token!)).durum).toBe("bekliyor");
  });

  it("onaylanınca aktif olur ve dönem sonu verir", async () => {
    const { s, token } = await aktifAbonelikKur();
    const sonuc = await s.abonelikSonucuAl(token);
    expect(sonuc.durum).toBe("aktif");
    expect(sonuc.abonelikRef).toBeTruthy();
    expect(sonuc.donemSonu).toBeGreaterThan(Date.now());
  });

  it("reddedilince ödenmedi olur", async () => {
    const s = sahteAbonelik("http://localhost:3000");
    const baslat = await s.abonelikBaslat(GIRDI);
    s.sahteAbonelikKarar(baslat.token!, "basarisiz");
    expect((await s.abonelikSonucuAl(baslat.token!)).durum).toBe("odenmedi");
  });

  /* Gerçekte yenilemeyi sağlayıcı yürütüyor; testte bir ay beklenemez. */
  it("yenileme dönem sonunu ileri taşır", async () => {
    const { s, ref } = await aktifAbonelikKur();
    const once = (await s.abonelikDurumAl(ref)).donemSonu!;

    expect(s.sahteAbonelikYenile(ref)).toBe(true);

    const sonra = (await s.abonelikDurumAl(ref)).donemSonu!;
    expect(sonra).toBeGreaterThan(once);
  });

  it("yenileme başarısız olursa ödenmedi işaretler", async () => {
    const { s, ref } = await aktifAbonelikKur();
    s.sahteAbonelikOdenmedi(ref);
    expect((await s.abonelikDurumAl(ref)).durum).toBe("odenmedi");
  });

  it("iptal edilen abonelik yenilenmez", async () => {
    const { s, ref } = await aktifAbonelikKur();
    expect((await s.abonelikIptal(ref)).ok).toBe(true);
    expect((await s.abonelikDurumAl(ref)).durum).toBe("iptal");
    // İptalden sonra yenileme çalışmamalı; aksi hâlde iptal anlamsız olur.
    expect(s.sahteAbonelikYenile(ref)).toBe(false);
  });

  it("bilinmeyen referansı tanımaz", async () => {
    const s = sahteAbonelik("http://localhost:3000");
    expect((await s.abonelikDurumAl("yok")).ok).toBe(false);
    expect((await s.abonelikIptal("yok")).ok).toBe(false);
  });
});
