import { DemoDriver } from "../../../shared/demo-driver";
import { HEAD_YAW_LIMIT_DEG } from "../../../shared/limits";
import type { Command, ServerMessage, Telemetry } from "../../../shared/protocol";

/**
 * Konsolun telemetri kaynağı.
 *
 * İki uygulaması vardır ve hangisinin çalıştığı ortama göre belirlenir:
 *
 *  - `WebSocketSource`: yerel ağda, Fastify sunucusu üzerinden. Faz 2'de aynı
 *    bağlantının ucunda gerçek robot olacak.
 *  - `BrowserMockSource`: sunucu yokken — örneğin site statik olarak Vercel'de
 *    yayımlandığında. Sunucusuz barındırmada kalıcı WebSocket kurulamaz, bu yüzden
 *    senaryo tarayıcıda koşar.
 *
 * İkisi de aynı `DemoDriver` beynini kullanır, iki ayrı senaryo yazılmaz.
 */
export interface ConsoleSource {
  readonly kind: "websocket" | "browser";
  onTelemetry(listener: (telemetry: Telemetry) => void): void;
  send(command: Command): void;
  stop(): void;
}

/** Sunucuya bağlanmayı dener; kuramazsa tarayıcı içi kaynağa düşer. */
export function connectTelemetry(
  onSource: (source: ConsoleSource) => void,
  timeoutMs = 1500,
): void {
  const url = `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws`;
  let settled = false;

  const fallback = (): void => {
    if (settled) return;
    settled = true;
    onSource(new BrowserMockSource());
  };

  let socket: WebSocket;
  try {
    socket = new WebSocket(url);
  } catch {
    fallback();
    return;
  }

  const timer = setTimeout(() => {
    if (settled) return;
    socket.close();
    fallback();
  }, timeoutMs);

  socket.addEventListener("open", () => {
    if (settled) return;
    settled = true;
    clearTimeout(timer);
    onSource(new WebSocketSource(socket));
  });

  socket.addEventListener("error", () => {
    clearTimeout(timer);
    fallback();
  });
}

class WebSocketSource implements ConsoleSource {
  readonly kind = "websocket" as const;
  private listener: ((telemetry: Telemetry) => void) | null = null;

  constructor(private readonly socket: WebSocket) {
    socket.addEventListener("message", (event) => {
      const message = JSON.parse(String(event.data)) as ServerMessage;
      if (message.kind === "telemetry") this.listener?.(message.payload);
    });
  }

  onTelemetry(listener: (telemetry: Telemetry) => void): void {
    this.listener = listener;
  }

  send(command: Command): void {
    if (this.socket.readyState === WebSocket.OPEN) {
      this.socket.send(JSON.stringify(command));
    }
  }

  stop(): void {
    this.socket.close();
  }
}

/**
 * Sunucu yokken senaryoyu tarayıcıda koşturur.
 *
 * Sunucudaki `MockSource` ile aynı davranışı üretir; farkı yalnızca nerede
 * çalıştığıdır. Ürettiği paketler `source: "mock"` taşır ve arayüz bunu gizlemez.
 */
class BrowserMockSource implements ConsoleSource {
  readonly kind = "browser" as const;
  private readonly driver = new DemoDriver();
  private readonly timer: number;
  private listener: ((telemetry: Telemetry) => void) | null = null;
  private eStop = false;
  private manualYaw: number | null = null;
  private actualYaw = 0;

  constructor(hz = 10) {
    const period = 1000 / hz;
    this.timer = window.setInterval(() => this.emit(period / 1000), period);
  }

  onTelemetry(listener: (telemetry: Telemetry) => void): void {
    this.listener = listener;
  }

  send(command: Command): void {
    switch (command.kind) {
      case "estop":
        this.eStop = command.engaged;
        if (command.engaged) this.manualYaw = this.actualYaw;
        break;
      case "head.center":
        this.manualYaw = 0;
        break;
      case "head.target":
        this.manualYaw = clamp(command.yawDeg, -HEAD_YAW_LIMIT_DEG, HEAD_YAW_LIMIT_DEG);
        break;
    }
  }

  stop(): void {
    window.clearInterval(this.timer);
  }

  private emit(dt: number): void {
    const state = this.driver.update(dt);
    const desired = this.eStop ? this.actualYaw : (this.manualYaw ?? state.headYawDeg);
    this.actualYaw += (desired - this.actualYaw) * 0.35;

    this.listener?.({
      t: Date.now(),
      source: "mock",
      connected: true,
      head: {
        desiredYawDeg: round(desired),
        actualYawDeg: round(this.actualYaw),
        encoderOk: true,
      },
      gaze: {
        attentionOwner: state.faceVisible ? "visual" : state.vad ? "audio" : "none",
        visualValid: state.faceVisible,
        state: this.eStop
          ? "ESTOP"
          : state.faceVisible
            ? "TRACKING"
            : state.vad
              ? "ORIENTING"
              : "IDLE",
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
    });
  }
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

function round(value: number): number {
  return Math.round(value * 100) / 100;
}
