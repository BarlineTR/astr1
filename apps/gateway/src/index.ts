import fastifyWebsocket from "@fastify/websocket";
import Fastify from "fastify";

import { HEAD_YAW_LIMIT_DEG, PROTOCOL_VERSION } from "@astro/protocol";
import type { ServerMessage } from "@astro/protocol";

import { parseCommand } from "./command";
import { MockSource } from "./telemetry/mock";
import type { TelemetrySource } from "./telemetry/source";

const PORT = Number(process.env.PORT ?? 8420);
const HOST = process.env.HOST ?? "0.0.0.0";

/**
 * Şimdilik telemetri sentetiktir.
 *
 * Faz 4'te burası `new BridgeSource(...)` olacak ve `astro_web` ROS düğümüne
 * bağlanacak. Sunucunun geri kalanında değişen tek şey bu satırdır — sözleşme
 * `@astro/protocol` içinde sabittir.
 */
const source: TelemetrySource = new MockSource();

const app = Fastify({ logger: { level: process.env.LOG_LEVEL ?? "info" } });

await app.register(fastifyWebsocket);

app.get("/saglik", async () => ({ ok: true, kaynak: "mock" }));

app.get("/ws", { websocket: true }, (socket) => {
  const hello: ServerMessage = {
    kind: "hello",
    // Ana sürüm uyuşmazsa karşı taraf bağlantıyı reddeder; sessizce yanlış
    // alan okumaktan iyidir.
    v: PROTOCOL_VERSION,
    source: "mock",
    limits: { headYawDeg: HEAD_YAW_LIMIT_DEG },
  };
  socket.send(JSON.stringify(hello));

  const unsubscribe = source.subscribe((telemetry) => {
    if (socket.readyState !== socket.OPEN) return;
    const message: ServerMessage = { kind: "telemetry", payload: telemetry };
    socket.send(JSON.stringify(message));
  });

  socket.on("message", (raw: Buffer) => {
    // İstemciden gelen her şey şüphelidir: sözleşmeye uymayan komut robota
    // hiç ulaşmaz. Kaynak sınırları ayrıca zorlar.
    const sonuc = parseCommand(raw.toString());
    if (!sonuc.ok) {
      const error: ServerMessage = { kind: "error", message: sonuc.message };
      socket.send(JSON.stringify(error));
      return;
    }
    source.send(sonuc.command);
  });

  socket.on("close", unsubscribe);
});

const shutdown = async (): Promise<void> => {
  source.stop();
  await app.close();
  process.exit(0);
};
process.on("SIGINT", shutdown);
process.on("SIGTERM", shutdown);

await app.listen({ port: PORT, host: HOST });
