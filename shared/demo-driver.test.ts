import { describe, expect, it } from "vitest";

import { AUDIO_CHAT_CONE_DEG, AUDIO_REACHABLE_DEG, HEAD_YAW_LIMIT_DEG } from "./limits";
import {
  DemoDriver,
  IDLE_BEFORE_FIRST_EVENT_S,
  IDLE_SWAY_DEG,
  PERSISTENCE_S,
  type DemoEvent,
} from "./demo-driver";

const STEP = 1 / 60;

/** Sürücüyü sabit adımlarla koşturur ve her karedeki kafa açısını döndürür. */
function run(driver: DemoDriver, seconds: number): number[] {
  const samples: number[] = [];
  for (let t = 0; t < seconds; t += STEP) samples.push(driver.update(STEP).headYawDeg);
  return samples;
}

/** Bir olayın kafayı hedefine ne zaman getirdiği (saniye); hiç getirmediyse null. */
function timeToReach(samples: number[], targetDeg: number, toleranceDeg = 3): number | null {
  const index = samples.findIndex((yaw) => Math.abs(yaw - targetDeg) <= toleranceDeg);
  return index === -1 ? null : index * STEP;
}

describe("DemoDriver — akustik zarf kuralı", () => {
  it("sohbet konisi içindeki sesi ısrar beklemeden kabul eder", () => {
    const bearing = 38;
    expect(Math.abs(bearing)).toBeLessThanOrEqual(AUDIO_CHAT_CONE_DEG);

    const samples = run(new DemoDriver([{ bearingDeg: bearing, durationS: 2.4 }]), 8);
    const reached = timeToReach(samples, bearing);

    expect(reached).not.toBeNull();
    // Boşta bekleme + dönüş süresi kadar; ısrar süresi eklenmemeli.
    expect(reached!).toBeLessThan(IDLE_BEFORE_FIRST_EVENT_S + PERSISTENCE_S);
  });

  it("75°–121° arasındaki sesi kabul etmeden önce ısrar bekler", () => {
    const bearing = 104;
    expect(Math.abs(bearing)).toBeGreaterThan(AUDIO_CHAT_CONE_DEG);
    expect(Math.abs(bearing)).toBeLessThanOrEqual(AUDIO_REACHABLE_DEG);

    const event: DemoEvent = { bearingDeg: bearing, durationS: 2.8 };
    const wide = timeToReach(run(new DemoDriver([event]), 10), HEAD_YAW_LIMIT_DEG);
    const near = timeToReach(run(new DemoDriver([{ bearingDeg: 38, durationS: 2.4 }]), 10), 38);

    expect(wide).not.toBeNull();
    expect(near).not.toBeNull();
    // Aradaki fark ısrar süresi kadar olmalı; dönüş yolu da uzadığı için
    // en az o kadar, ama makul bir üst sınırın altında.
    expect(wide! - near!).toBeGreaterThanOrEqual(PERSISTENCE_S * 0.9);
  });

  it("erişilemeyen açıya kafayı hiç çevirmez", () => {
    // 121° = kafa limiti 85 + kamera yarı görüş açısı 36. Ötesi kadraja giremez.
    const bearing = -152;
    expect(Math.abs(bearing)).toBeGreaterThan(AUDIO_REACHABLE_DEG);

    const samples = run(new DemoDriver([{ bearingDeg: bearing, durationS: 2.0 }]), 12);
    const largest = Math.max(...samples.map(Math.abs));

    // Kafa yalnızca boşta gezinme genliği kadar oynamalı.
    expect(largest).toBeLessThanOrEqual(IDLE_SWAY_DEG + 1);
  });

  it("hiçbir durumda güvenli açı aralığını aşmaz", () => {
    const samples = run(
      new DemoDriver([
        { bearingDeg: 118, durationS: 2.5 },
        { bearingDeg: -110, durationS: 2.5 },
      ]),
      30,
    );

    for (const yaw of samples) {
      expect(Math.abs(yaw)).toBeLessThanOrEqual(HEAD_YAW_LIMIT_DEG);
    }
  });

  it("erişilebilir ama limit dışı bir kerterizi limite kırpar", () => {
    const samples = run(new DemoDriver([{ bearingDeg: 118, durationS: 2.5 }]), 10);
    // Kerteriz 118°, limit 85°: kafa limitte durur ve orada kalır.
    expect(Math.max(...samples)).toBeCloseTo(HEAD_YAW_LIMIT_DEG, 1);
  });

  it("boş senaryoyu reddeder", () => {
    expect(() => new DemoDriver([])).toThrow();
  });
});
