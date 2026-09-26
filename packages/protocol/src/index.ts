/**
 * `@astro/protocol` — sözleşmenin **çalışma zamanı bedeli olmayan** girişi.
 *
 * Burada yalnızca sabitler, sahne tipleri ve şemalardan türetilen tipler var.
 * zod bilerek dışarıda: sözleşmeyi doğrulamak ağ geçidinin işi, tarayıcının
 * değil. Şemalar tek bir dosyadan da verilse, bu girişten sızan zod her
 * ziyaretçiye 28,5 KB (gz) olarak inmişti — ölçüldü, sonra ayrıldı.
 *
 * Doğrulamaya ihtiyacı olan taraf `@astro/protocol/schema`yı alır.
 */

export * from "./limits";
export * from "./scene-state";
export * from "./version";
export { DemoDriver } from "./demo-driver";

export type {
  AttentionOwner,
  AudioTelemetry,
  Command,
  FaceObservation,
  GazeTelemetry,
  HeadTelemetry,
  SafetyTelemetry,
  ServerMessage,
  Telemetry,
  TelemetrySource,
} from "./schema";
