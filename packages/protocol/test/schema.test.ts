import { describe, expect, it } from "vitest";

import { protocolJsonSchema } from "../src/json-schema";
import { HEAD_YAW_LIMIT_DEG } from "../src/limits";
import { commandSchema, telemetrySchema } from "../src/schema";
import { PROTOCOL_VERSION } from "../src/version";

/** Ağ geçidinin robota yollayacağı örnek: alanların hepsi dolu. */
const gecerliTelemetri = {
  t: 1_759_000_000_000,
  source: "mock",
  connected: true,
  head: { desiredYawDeg: 12.5, actualYawDeg: 11.8, encoderOk: true },
  gaze: { attentionOwner: "visual", visualValid: true, state: "TRACKING" },
  audio: { doaDeg: -30, confidence: 0.8, vad: true },
  faces: [{ name: "Ada", confidence: 0.91, box: [0.1, 0.2, 0.3, 0.4], distanceM: 1.2 }],
  safety: { eStop: false, watchdogOk: true },
};

describe("telemetrySchema", () => {
  it("geçerli telemetriyi kabul eder", () => {
    expect(telemetrySchema.parse(gecerliTelemetri)).toMatchObject({ source: "mock" });
  });

  it("tanınmayan dikkat sahibini reddeder", () => {
    const bozuk = {
      ...gecerliTelemetri,
      gaze: { ...gecerliTelemetri.gaze, attentionOwner: "kulak" },
    };
    expect(() => telemetrySchema.parse(bozuk)).toThrow();
  });

  it("kutu dört elemandan kısa olamaz", () => {
    const bozuk = {
      ...gecerliTelemetri,
      faces: [{ ...gecerliTelemetri.faces[0], box: [0.1, 0.2] }],
    };
    expect(() => telemetrySchema.parse(bozuk)).toThrow();
  });
});

describe("commandSchema", () => {
  it("sınır içindeki hedefi kabul eder", () => {
    expect(commandSchema.parse({ kind: "head.target", yawDeg: 40 })).toEqual({
      kind: "head.target",
      yawDeg: 40,
    });
  });

  /*
   * Kırpma köprüde yapılır ama şema yine de sınırı zorlar: istemciye
   * güvenilmediği için iki katman da gerekli.
   */
  it("sınırın ötesindeki hedefi reddeder", () => {
    expect(() =>
      commandSchema.parse({ kind: "head.target", yawDeg: HEAD_YAW_LIMIT_DEG + 1 }),
    ).toThrow();
  });

  it("tanınmayan komut türünü reddeder", () => {
    expect(() => commandSchema.parse({ kind: "kafa.patlat" })).toThrow();
  });
});

describe("protocolJsonSchema", () => {
  /*
   * ROS tarafındaki Python ajanı bu şemaya karşı kendi testini koşar. Üretimin
   * çalıştığını burada doğrulamak, iki depo arasındaki tek bağın kopmadığını
   * garanti eder.
   */
  it("sürüm taşıyan bir JSON Schema üretir", () => {
    const schema = protocolJsonSchema();
    expect(schema.$id).toContain(PROTOCOL_VERSION);
    expect(schema.$defs).toHaveProperty("Telemetry");
    expect(schema.$defs).toHaveProperty("Command");
  });
});
