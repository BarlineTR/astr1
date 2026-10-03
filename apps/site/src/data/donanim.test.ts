import { describe, expect, it } from "vitest";

import {
  DONANIM_AKSAMALARI,
  ROBOT_SISTEM_OZETI,
  STABILITE_METRIKLERI,
} from "./donanim";

describe("donanim verisi ve stabilite metrikleri", () => {
  it("robot sistem ozetinde tum alanlar tutarli olmali", () => {
    expect(ROBOT_SISTEM_OZETI.kodAdi).toBe("ASTRO-V1");
    expect(ROBOT_SISTEM_OZETI.stabiliteSkoru).toBeGreaterThanOrEqual(95);
    expect(ROBOT_SISTEM_OZETI.donguFrekansiHz).toBe(50);
    expect(ROBOT_SISTEM_OZETI.toplamAksamSayisi).toBe(DONANIM_AKSAMALARI.length);
    expect(ROBOT_SISTEM_OZETI.calisanAksamSayisi).toBe(DONANIM_AKSAMALARI.length);
  });

  it("tum calisan aksamlar gerekli alanlari ve olcum kaynaklarini icermeli", () => {
    expect(DONANIM_AKSAMALARI.length).toBeGreaterThanOrEqual(6);

    for (const aksam of DONANIM_AKSAMALARI) {
      expect(aksam.id).toBeTruthy();
      expect(aksam.ad).toBeTruthy();
      expect(aksam.model).toBeTruthy();
      expect(["algi", "hareket", "islem", "guvenlik"]).toContain(aksam.kategori);
      expect(aksam.calismaFrekansi).toBeTruthy();
      expect(aksam.birincilMetrik.etiket).toBeTruthy();
      expect(aksam.birincilMetrik.deger).toBeTruthy();
      expect(aksam.ikincilMetrik.etiket).toBeTruthy();
      expect(aksam.ikincilMetrik.deger).toBeTruthy();
      expect(aksam.olcumKaynagi).toBeTruthy();
    }
  });

  it("stabilite metrikleri olculmus degerler ve guvenli araliklar tasimali", () => {
    expect(STABILITE_METRIKLERI.length).toBeGreaterThanOrEqual(5);

    for (const metrik of STABILITE_METRIKLERI) {
      expect(metrik.id).toBeTruthy();
      expect(metrik.baslik).toBeTruthy();
      expect(metrik.nominalDeger).toBeTruthy();
      expect(metrik.tolerans).toBeTruthy();
      expect(metrik.birim).toBeTruthy();
      expect(metrik.kaynak).toBeTruthy();
      expect(["stabil", "kontrol-altinda", "guvenli"]).toContain(metrik.durum);
    }
  });
});
