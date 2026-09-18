import { HEAD_YAW_LIMIT_DEG, AUDIO_CHAT_CONE_DEG, AUDIO_REACHABLE_DEG } from "./limits";
import type { SceneDriver, SceneState } from "./scene-state";

/**
 * Giriş sayfasındaki senaryolu sürücü.
 *
 * Bu bir süs animasyonu değil, kararın anlatımıdır ve gerçek kuralı uygular:
 * 75°'lik sohbet konisi içindeki bir ses anında geçer; 75° ile 121° arası ısrar
 * ister — çünkü bu aralıkta yankıyı insandan ayırmak gerekir. 121°'nin ötesi
 * hiç denenmez: kafa limiti 85° artı kamera yarı görüş açısı 36° ile kadraja
 * girebilecek en geniş açı odur, ötesi gövde dönüşü ister ve gövde dönüşü yoktur.
 *
 * Gerçek robotta hız sınırı firmware'dedir; buradaki yumuşatma yalnızca görsel
 * karşılığıdır, bir planlayıcı çıktısı değildir.
 */

type Phase = "idle" | "listening" | "turning" | "engaged" | "releasing";

/** Kafanın görsel dönüş hızı (°/s). Firmware'deki gerçek sınırın karşılığı değil. */
const TURN_RATE_DEG_S = 62;

/** 75°–121° arasındaki bir sesin kabul edilmesi için gereken ısrar süresi (s). */
export const PERSISTENCE_S = 0.9;

/** Boşta gezinme genliği (derece). Gerçek limit ±85°, ama boşta kafa sakin durur. */
export const IDLE_SWAY_DEG = 16;

/** Hedef kilitliyken kafanın oynadığı dar bant (derece). */
export const ENGAGED_SWAY_DEG = 2.6;

/** Senaryonun ilk olaydan önce boşta beklediği süre (s). */
export const IDLE_BEFORE_FIRST_EVENT_S = 3.2;

export interface DemoEvent {
  bearingDeg: number;
  /** Ses bu kadar saniye sürer. */
  durationS: number;
}

/**
 * Giriş sayfasının anlatısı: sırayla yakın sohbet açısı, geniş ama erişilebilir
 * açı, erişilemeyen açı. Sabittir — her ziyaretçi aynı anlatıyı görür.
 */
export const DEFAULT_DEMO_EVENTS: readonly DemoEvent[] = [
  { bearingDeg: 38, durationS: 2.4 },
  { bearingDeg: -66, durationS: 2.2 },
  { bearingDeg: 104, durationS: 2.8 },
  { bearingDeg: -152, durationS: 2.0 },
];

export class DemoDriver implements SceneDriver {
  private phase: Phase = "idle";
  private elapsed = 0;
  private headYaw = 0;
  private targetYaw = 0;
  private event: DemoEvent | null = null;
  private persistence = 0;
  private vadLevel = 0;
  private faceVisible = false;
  private swayPhase = Math.random() * Math.PI * 2;
  private readonly queue: readonly DemoEvent[];
  private queueIndex = 0;

  /** Senaryo dışarıdan verilebilir; testler tek olaylı bir kuyrukla çalışır. */
  constructor(events: readonly DemoEvent[] = DEFAULT_DEMO_EVENTS) {
    if (events.length === 0) throw new Error("Demo senaryosu boş olamaz");
    this.queue = events;
  }

  update(dt: number): SceneState {
    this.elapsed += dt;
    this.swayPhase += dt * 0.35;

    switch (this.phase) {
      case "idle":
        this.updateIdle();
        break;
      case "listening":
        this.updateListening(dt);
        break;
      case "turning":
        this.updateTurning();
        break;
      case "engaged":
        this.updateEngaged();
        break;
      case "releasing":
        this.updateReleasing();
        break;
    }

    this.headYaw = approach(this.headYaw, this.targetYaw, TURN_RATE_DEG_S * dt);

    return {
      headYawDeg: this.headYaw,
      doaDeg: this.event ? this.event.bearingDeg : null,
      vad: this.vadLevel > 0.02,
      faceVisible: this.faceVisible,
    };
  }

  /** Boşta: kafa yavaşça salınır. Gerçek limit ±85°, ama boşta sakin durur. */
  private updateIdle(): void {
    this.targetYaw = Math.sin(this.swayPhase) * IDLE_SWAY_DEG;
    this.vadLevel = 0;
    this.faceVisible = false;
    if (this.elapsed > IDLE_BEFORE_FIRST_EVENT_S) this.beginNextEvent();
  }

  private updateListening(dt: number): void {
    const event = this.event;
    if (!event) return this.toPhase("idle");

    this.vadLevel = Math.min(1, this.vadLevel + dt * 4);
    const bearing = Math.abs(event.bearingDeg);

    if (bearing > AUDIO_REACHABLE_DEG) {
      // Kadraja giremez. Kafa denemez bile; ses duyulur ve bırakılır.
      if (this.elapsed > event.durationS) this.toPhase("releasing");
      return;
    }

    if (bearing <= AUDIO_CHAT_CONE_DEG) {
      this.commitTurn(event.bearingDeg);
      return;
    }

    // 75°–121°: ısrar bekleniyor.
    this.persistence += dt;
    if (this.persistence >= PERSISTENCE_S) this.commitTurn(event.bearingDeg);
  }

  private commitTurn(bearingDeg: number): void {
    this.targetYaw = clamp(bearingDeg, -HEAD_YAW_LIMIT_DEG, HEAD_YAW_LIMIT_DEG);
    this.toPhase("turning");
  }

  private updateTurning(): void {
    this.vadLevel = Math.max(0, this.vadLevel - 0.01);
    if (Math.abs(this.headYaw - this.targetYaw) < 1.2) {
      this.faceVisible = true;
      this.toPhase("engaged");
    }
  }

  private updateEngaged(): void {
    // Hedef kilitliyken kafa, yüzün küçük hareketlerini takip ediyormuş gibi
    // dar bir bantta oynar.
    // Kırpma en sona uygulanır. Önce kırpıp sonra salınım eklemek, limitte
    // kilitlenmiş bir hedefte kafayı aralığın dışına taşıyordu (ölçüldü: 87,6°).
    const base = this.event ? this.event.bearingDeg : 0;
    this.targetYaw = clamp(
      base + Math.sin(this.swayPhase * 2.1) * ENGAGED_SWAY_DEG,
      -HEAD_YAW_LIMIT_DEG,
      HEAD_YAW_LIMIT_DEG,
    );
    this.vadLevel = Math.max(0, this.vadLevel - 0.02);
    if (this.elapsed > 2.6) this.toPhase("releasing");
  }

  private updateReleasing(): void {
    this.faceVisible = false;
    this.vadLevel = Math.max(0, this.vadLevel - 0.05);
    this.targetYaw = 0;
    if (this.elapsed > 1.4) {
      this.event = null;
      this.toPhase("idle");
    }
  }

  private beginNextEvent(): void {
    const next = this.queue[this.queueIndex % this.queue.length];
    this.queueIndex += 1;
    this.event = next ?? null;
    this.persistence = 0;
    this.toPhase("listening");
  }

  private toPhase(phase: Phase): void {
    this.phase = phase;
    this.elapsed = 0;
  }
}

function approach(current: number, target: number, maxStep: number): number {
  const delta = target - current;
  if (Math.abs(delta) <= maxStep) return target;
  return current + Math.sign(delta) * maxStep;
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}
