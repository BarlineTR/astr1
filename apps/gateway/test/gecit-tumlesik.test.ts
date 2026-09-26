import { spawn, type ChildProcess } from "node:child_process";
import { createServer, type Server } from "node:http";
import { once } from "node:events";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { WebSocket } from "ws";

import { PROTOCOL_VERSION } from "@astro/protocol";

/**
 * Ağ geçidinin uçtan uca sınanması.
 *
 * Gerçek süreç ayağa kaldırılıyor ve sitenin doğrulama ucu sahte bir HTTP
 * sunucusuyla taklit ediliyor: ağ geçidinin veritabanına ihtiyacı yok, tek
 * bağımlılığı o uç. Böylece protokol davranışı Next ve Postgres olmadan
 * sınanabiliyor.
 */

const SIR = "test-gecit-sirri";
const GECIT_PORT = 8499;
const SITE_PORT = 8498;

let site: Server;
let gecit: ChildProcess;

/** Sahte site: bilinen jetonları tanır, ötekini reddeder. */
function sahteSite(): Server {
  return createServer((istek, yanit) => {
    if (istek.headers["x-gecit-sirri"] !== SIR) {
      yanit.writeHead(401).end("{}");
      return;
    }

    let govde = "";
    istek.on("data", (p) => (govde += p));
    istek.on("end", () => {
      const { tur, token } = JSON.parse(govde) as { tur: string; token: string };
      yanit.writeHead(200, { "content-type": "application/json" });

      if (tur === "cihaz" && token === "gecerli-cihaz-jetonu") {
        yanit.end(JSON.stringify({ ok: true, cihazId: "cihaz-1", serial: "TEST-1" }));
      } else if (tur === "panel" && token === "gecerli-panel-jetonu") {
        yanit.end(
          JSON.stringify({
            ok: true,
            cihazId: "cihaz-1",
            kullaniciId: "kullanici-1",
            komutVerebilir: true,
          }),
        );
      } else if (tur === "panel" && token === "izleyici-jetonu-uzun-yeterli") {
        yanit.end(
          JSON.stringify({
            ok: true,
            cihazId: "cihaz-1",
            kullaniciId: "kullanici-2",
            komutVerebilir: false,
          }),
        );
      } else {
        yanit.end(JSON.stringify({ ok: false }));
      }
    });
  });
}

function baglan(yol: string): Promise<WebSocket> {
  const ws = new WebSocket(`ws://127.0.0.1:${GECIT_PORT}${yol}`);
  return once(ws, "open").then(() => ws);
}

/** Belirli bir çerçeve türü gelene kadar bekler; nabız çerçevelerini atlar. */
function cerceveBekle(ws: WebSocket, tur: string, zamanAsimiMs = 5000): Promise<any> {
  return new Promise((coz, reddet) => {
    const zamanlayici = setTimeout(() => {
      ws.off("message", dinleyici);
      reddet(new Error(`"${tur}" çerçevesi ${zamanAsimiMs} ms içinde gelmedi`));
    }, zamanAsimiMs);

    function dinleyici(ham: Buffer) {
      const c = JSON.parse(ham.toString());
      if (c.kind !== tur) return;
      clearTimeout(zamanlayici);
      ws.off("message", dinleyici);
      coz(c);
    }

    ws.on("message", dinleyici);
  });
}

beforeAll(async () => {
  site = sahteSite();
  site.listen(SITE_PORT);
  await once(site, "listening");

  gecit = spawn("node", ["apps/gateway/dist/index.js"], {
    env: {
      ...process.env,
      PORT: String(GECIT_PORT),
      HOST: "127.0.0.1",
      SITE_URL: `http://127.0.0.1:${SITE_PORT}`,
      GATEWAY_SHARED_SECRET: SIR,
      LOG_LEVEL: "silent",
    },
    stdio: "ignore",
  });

  // Sağlık ucu cevap verene kadar bekle.
  for (let i = 0; i < 60; i++) {
    try {
      const y = await fetch(`http://127.0.0.1:${GECIT_PORT}/saglik`);
      if (y.ok) return;
    } catch {
      /* henüz açılmadı */
    }
    await new Promise((r) => setTimeout(r, 200));
  }
  throw new Error("ağ geçidi açılmadı");
}, 30_000);

afterAll(async () => {
  gecit?.kill();
  site?.close();
});

describe("cihaz ucu", () => {
  it("geçerli jetonla kabul eder", async () => {
    const ws = await baglan("/ws/cihaz");
    ws.send(
      JSON.stringify({
        kind: "cihaz.merhaba",
        v: PROTOCOL_VERSION,
        token: "gecerli-cihaz-jetonu",
        firmware: "test-1.0",
      }),
    );

    const kabul = await cerceveBekle(ws, "gecit.kabul");
    expect(kabul.cihazId).toBe("cihaz-1");
    expect(kabul.limits.headYawDeg).toBe(85);
    ws.close();
  });

  /* Kısa jetonlar kimlik kontrolüne hiç ulaşmadan şemada elenir; bu test
     sözleşmeyi geçen ama tanınmayan bir jetonu sınıyor. */
  it("geçersiz jetonu reddeder", async () => {
    const ws = await baglan("/ws/cihaz");
    ws.send(
      JSON.stringify({ kind: "cihaz.merhaba", v: PROTOCOL_VERSION, token: "yanlis-jeton-ama-yeterince-uzun" }),
    );

    const hata = await cerceveBekle(ws, "gecit.hata");
    expect(hata.kod).toBe("jeton-gecersiz");
    ws.close();
  });

  /* Sessizce devam edip yanlış alan okumak, bir robot sisteminde en kötü davranış. */
  it("farklı ana sürümü reddeder", async () => {
    const ws = await baglan("/ws/cihaz");
    ws.send(
      JSON.stringify({ kind: "cihaz.merhaba", v: "99", token: "gecerli-cihaz-jetonu" }),
    );

    const hata = await cerceveBekle(ws, "gecit.hata");
    expect(hata.kod).toBe("surum-uyusmazligi");
    ws.close();
  });

  it("merhaba gelmeden telemetriyi işlemez", async () => {
    const ws = await baglan("/ws/cihaz");
    ws.send(JSON.stringify({ kind: "cihaz.telemetri", payload: ornekTelemetri() }));

    const hata = await cerceveBekle(ws, "gecit.hata");
    expect(hata.kod).toBe("jeton-gecersiz");
    ws.close();
  });

  /* Jetonu ele geçirilmiş bir ajan bozuk telemetri basabilir; panel onu gerçek sanardı. */
  it("sözleşmeye uymayan telemetriyi reddeder", async () => {
    const ws = await baglan("/ws/cihaz");
    ws.send(
      JSON.stringify({
        kind: "cihaz.merhaba",
        v: PROTOCOL_VERSION,
        token: "gecerli-cihaz-jetonu",
      }),
    );
    await cerceveBekle(ws, "gecit.kabul");

    const bozuk = ornekTelemetri();
    (bozuk as any).head.actualYawDeg = "on beş derece";
    ws.send(JSON.stringify({ kind: "cihaz.telemetri", payload: bozuk }));

    const hata = await cerceveBekle(ws, "gecit.hata");
    expect(hata.kod).toBe("sozlesme-disi");
    ws.close();
  });
});

describe("panel ucu", () => {
  it("telemetriyi cihazdan panele iletir", async () => {
    const cihaz = await baglan("/ws/cihaz");
    cihaz.send(
      JSON.stringify({
        kind: "cihaz.merhaba",
        v: PROTOCOL_VERSION,
        token: "gecerli-cihaz-jetonu",
      }),
    );
    await cerceveBekle(cihaz, "gecit.kabul");

    const panel = await baglan("/ws/panel");
    panel.send(
      JSON.stringify({
        kind: "panel.merhaba",
        v: PROTOCOL_VERSION,
        token: "gecerli-panel-jetonu",
      }),
    );
    await cerceveBekle(panel, "gecit.panel-kabul");

    const t = ornekTelemetri();
    t.head.actualYawDeg = 42.5;
    cihaz.send(JSON.stringify({ kind: "cihaz.telemetri", payload: t }));

    const gelen = await cerceveBekle(panel, "gecit.telemetri");
    expect(gelen.payload.head.actualYawDeg).toBe(42.5);
    // Gecikme ölçümü ağ geçidinin damgasına dayanıyor, robotunkine değil.
    expect(typeof gelen.t).toBe("number");

    cihaz.close();
    panel.close();
  });

  it("komutu cihaza iletir ve onayı geri taşır", async () => {
    const cihaz = await baglan("/ws/cihaz");
    cihaz.send(
      JSON.stringify({
        kind: "cihaz.merhaba",
        v: PROTOCOL_VERSION,
        token: "gecerli-cihaz-jetonu",
      }),
    );
    await cerceveBekle(cihaz, "gecit.kabul");

    const panel = await baglan("/ws/panel");
    panel.send(
      JSON.stringify({
        kind: "panel.merhaba",
        v: PROTOCOL_VERSION,
        token: "gecerli-panel-jetonu",
      }),
    );
    await cerceveBekle(panel, "gecit.panel-kabul");

    panel.send(
      JSON.stringify({
        kind: "panel.komut",
        komutId: "k1",
        komut: { kind: "head.target", yawDeg: -40 },
      }),
    );

    const komut = await cerceveBekle(cihaz, "gecit.komut");
    expect(komut.komut.yawDeg).toBe(-40);
    expect(komut.komutId).toBe("k1");

    cihaz.send(JSON.stringify({ kind: "cihaz.onay", komutId: "k1", kabul: true }));
    const onay = await cerceveBekle(panel, "gecit.onay");
    expect(onay).toMatchObject({ komutId: "k1", kabul: true });

    cihaz.close();
    panel.close();
  });

  /* İzleyici yalnızca bakar; arayüz düğmeyi çizmese de soket doğrudan kullanılabilir. */
  it("izleyicinin komutunu reddeder", async () => {
    const panel = await baglan("/ws/panel");
    panel.send(
      JSON.stringify({ kind: "panel.merhaba", v: PROTOCOL_VERSION, token: "izleyici-jetonu-uzun-yeterli" }),
    );
    const kabul = await cerceveBekle(panel, "gecit.panel-kabul");
    expect(kabul.komutVerebilir).toBe(false);

    panel.send(
      JSON.stringify({
        kind: "panel.komut",
        komutId: "k1",
        komut: { kind: "head.center" },
      }),
    );

    const hata = await cerceveBekle(panel, "gecit.hata");
    expect(hata.kod).toBe("yetki-yok");
    panel.close();
  });

  /*
   * Robot bağlı değilken komut kuyruğa alınmaz: sonradan teslim edilen bir
   * hareket komutu, operatörün artık istemediği bir hareketi yaptırabilir.
   */
  it("robot bağlı değilken komutu kuyruğa almaz", async () => {
    const panel = await baglan("/ws/panel");
    panel.send(
      JSON.stringify({
        kind: "panel.merhaba",
        v: PROTOCOL_VERSION,
        token: "gecerli-panel-jetonu",
      }),
    );
    await cerceveBekle(panel, "gecit.panel-kabul");

    const durum = await cerceveBekle(panel, "gecit.cihaz-durum");
    expect(durum.bagli).toBe(false);

    panel.send(
      JSON.stringify({
        kind: "panel.komut",
        komutId: "k9",
        komut: { kind: "head.center" },
      }),
    );

    const onay = await cerceveBekle(panel, "gecit.onay");
    expect(onay).toMatchObject({ komutId: "k9", kabul: false });
    expect(onay.neden).toContain("bağlı değil");
    panel.close();
  });

  it("sınır dışı komutu sözleşmede yakalar", async () => {
    const panel = await baglan("/ws/panel");
    panel.send(
      JSON.stringify({
        kind: "panel.merhaba",
        v: PROTOCOL_VERSION,
        token: "gecerli-panel-jetonu",
      }),
    );
    await cerceveBekle(panel, "gecit.panel-kabul");

    panel.send(
      JSON.stringify({
        kind: "panel.komut",
        komutId: "k2",
        komut: { kind: "head.target", yawDeg: 999 },
      }),
    );

    const hata = await cerceveBekle(panel, "gecit.hata");
    expect(hata.kod).toBe("sozlesme-disi");
    panel.close();
  });
});

function ornekTelemetri() {
  return {
    t: Date.now(),
    source: "robot" as const,
    connected: true,
    head: { desiredYawDeg: 0, actualYawDeg: 0, encoderOk: true },
    gaze: { attentionOwner: "none" as const, visualValid: false, state: "IDLE" },
    audio: { doaDeg: null, confidence: 0, vad: false },
    faces: [],
    safety: { eStop: false, watchdogOk: true },
  };
}
