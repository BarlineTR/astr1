import type { Command, Telemetry } from "@astro/protocol";

/**
 * Telemetri kaynağı.
 *
 * Faz 1'de `MockSource`, faz 2'de `astro_web` ROS köprüsüne bağlanan
 * `BridgeSource` bu arayüzü karşılar. Sunucunun geri kalanı hangisinin bağlı
 * olduğunu bilmez; değişecek tek satır `index.ts` içindeki örnekleme satırıdır.
 */
export interface TelemetrySource {
  /** Yeni telemetri geldiğinde çağrılır. Dönen işlev aboneliği sonlandırır. */
  subscribe(listener: (telemetry: Telemetry) => void): () => void;
  /** İstemciden gelen komut. Kaynak sınırları kendisi zorlar. */
  send(command: Command): void;
  stop(): void;
}
