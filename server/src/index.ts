import { existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join, parse } from "node:path";

import fastifyStatic from "@fastify/static";
import fastifyWebsocket from "@fastify/websocket";
import Fastify from "fastify";

import { HEAD_YAW_LIMIT_DEG } from "../../shared/limits";
import type { Command, ServerMessage } from "../../shared/protocol";
import { MockSource } from "./telemetry/mock";
import type { TelemetrySource } from "./telemetry/source";

/**
 * İstemcinin derlenmiş çıktısını bulur.
 *
 * Sabit bir göreli yol yazılamaz: `tsx` ile kaynaktan koşarken bu dosya
 * `server/src` içindedir, derlendikten sonra `server/dist/server/src` içinde.
 * Yukarı doğru yürüyüp `client/dist`i aramak iki durumda da çalışır ve
 * bulunamadığında sessizce boş sayfa yerine anlaşılır bir hata verir.
 */
function findClientDist(): string {
  const override = process.env.CLIENT_DIST;
  if (override) return override;

  let current = dirname(fileURLToPath(import.meta.url));
  const { root } = parse(current);
  while (true) {
    const candidate = join(current, "client/dist");
    if (existsSync(candidate)) return candidate;
    if (current === root) break;
    current = dirname(current);
  }
  throw new Error(
    "client/dist bulunamadı. Önce `npm run build --workspace=client` çalıştırın " +
      "ya da CLIENT_DIST ortam değişkenini verin.",
  );
}

const CLIENT_DIST = findClientDist();

const PORT = Number(process.env.PORT ?? 8420);
const HOST = process.env.HOST ?? "0.0.0.0";

/**
 * Faz 1: telemetri sentetiktir.
 *
 * Faz 2'de burası `new BridgeSource(...)` olacak ve `astro_web` ROS düğümüne
 * bağlanacak. Sunucunun geri kalanında değişen tek şey bu satırdır — sözleşme
 * `shared/protocol.ts` içinde sabittir.
 */
const source: TelemetrySource = new MockSource();

const app = Fastify({ logger: { level: process.env.LOG_LEVEL ?? "info" } });

await app.register(fastifyWebsocket);
await app.register(fastifyStatic, { root: CLIENT_DIST });

app.get("/saglik", async () => ({ ok: true, kaynak: "mock" }));

/**
 * Temiz adresler. Vercel bunu `cleanUrls` ile kendisi yapar; yerel sunucunun
 * aynı adresleri vermesi, iki ortamda farklı bağlantılar denemek zorunda
 * kalmamak için gerekli.
 */
for (const [route, file] of [
  ["/hakkimizda", "hakkimizda.html"],
  ["/konsol", "konsol.html"],
] as const) {
  app.get(route, (_request, reply) => reply.sendFile(file));
}

app.get("/ws", { websocket: true }, (socket) => {
  const hello: ServerMessage = {
    kind: "hello",
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
    try {
      // İstemciden gelen her şey şüphelidir; kaynak sınırları ayrıca zorlar.
      source.send(JSON.parse(raw.toString()) as Command);
    } catch {
      const error: ServerMessage = { kind: "error", message: "Komut çözümlenemedi" };
      socket.send(JSON.stringify(error));
    }
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
