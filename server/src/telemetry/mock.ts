import { DemoDriver } from "@astro/protocol";
import { HEAD_YAW_LIMIT_DEG } from "@astro/protocol";
import type { Command, Telemetry } from "@astro/protocol";
import type { TelemetrySource } from "./source";

/**
 * Robot yokken arayüzü besleyen sentetik kaynak.
 *
 * Karar mantığı kopyalanmaz: giriş sayfasındaki sahneyi süren `DemoDriver`'ın
 * aynısı kullanılır. İki ayrı senaryo yazılsaydı biri kaçınılmaz olarak kayardı
 * ve konsolda görülen davranış tanıtımda anlatılanla çelişirdi.
 *
 * Ürettiği her paket `source: "mock"` taşır. Arayüzün bunu gizlememesi şart:
 * gerçek sanılan sahte telemetri, bu projenin en pahalı hata sınıfıdır.
 */
export class MockSource implements TelemetrySource {
  private readonly driver = new DemoDriver();
  private readonly listeners = new Set<(telemetry: Telemetry) => void>();
  private readonly timer: NodeJS.Timeout;
  private eStop = false;
  private manualYaw: number | null = null;
  private lastYaw = 0;

  /** @param hz yayın hızı. Görsel telemetri için 10 Hz yeterli; ham 50 Hz gereksiz. */
  constructor(private readonly hz = 10) {
    const period = 1000 / this.hz;
    this.timer = setInterval(() => this.emit(period / 1000), period);
  }

  subscribe(listener: (telemetry: Telemetry) => void): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  send(command: Command): void {
    switch (command.kind) {
      case "estop":
        this.eStop = command.engaged;
        if (command.engaged) this.manualYaw = this.lastYaw;
        break;
      case "head.center":
        this.manualYaw = 0;
        break;
      case "head.target":
        // Kırpma kaynakta yapılır; istemciye güvenilmez.
        this.manualYaw = clamp(command.yawDeg, -HEAD_YAW_LIMIT_DEG, HEAD_YAW_LIMIT_DEG);
        break;
    }
  }

  stop(): void {
    clearInterval(this.timer);
    this.listeners.clear();
  }

  private emit(dt: number): void {
    const state = this.driver.update(dt);

    // Acil durdurma kafayı olduğu yerde dondurur; elle hedef verilmişse senaryo
    // değil o hedef geçerlidir.
    const desired = this.eStop ? this.lastYaw : (this.manualYaw ?? state.headYawDeg);
    // Encoder gerçeği hedefi bir miktar geriden takip eder.
    this.lastYaw += (desired - this.lastYaw) * 0.35;

    const telemetry: Telemetry = {
      t: Date.now(),
      source: "mock",
      connected: true,
      head: {
        desiredYawDeg: round(desired),
        actualYawDeg: round(this.lastYaw),
        encoderOk: true,
      },
      gaze: {
        attentionOwner: state.faceVisible ? "visual" : state.vad ? "audio" : "none",
        visualValid: state.faceVisible,
        state: this.eStop ? "ESTOP" : state.faceVisible ? "TRACKING" : state.vad ? "ORIENTING" : "IDLE",
      },
      audio: {
        doaDeg: state.doaDeg === null ? null : round(state.doaDeg),
        confidence: state.vad ? 0.82 : 0.14,
        vad: state.vad,
      },
      faces: state.faceVisible
        ? [{ name: null, confidence: 0.78, box: [0.38, 0.3, 0.24, 0.32], distanceM: 1.4 }]
        : [],
      safety: { eStop: this.eStop, watchdogOk: true },
    };

    for (const listener of this.listeners) listener(telemetry);
  }
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

function round(value: number): number {
  return Math.round(value * 100) / 100;
}
