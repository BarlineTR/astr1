#!/usr/bin/env node
/**
 * Referans robot ajanı — **test içindir**.
 *
 * Gerçek ajan robot tarafında Python/ROS olarak yazılacak ve bu depoda değil,
 * ROS dalında duracak (tasarım belgesi D6). Bu betik portun gerçekten
 * çalıştığını robot olmadan göstermek ve sözleşmeyi örneklemek için var.
 *
 * Kullanım:
 *   node tools/sahte-robot.mjs --kod ABCD-EFGH-JKMN-PQRS --seri ASTRO-V1-000123
 *   node tools/sahte-robot.mjs --jeton <daha önce alınmış jeton>
 *
 * Akış:
 *   1. Kod varsa siteye POST /api/cihaz/eslestir → uzun ömürlü jeton
 *   2. Ağ geçidine wss/ws .../ws/cihaz ile bağlan
 *   3. cihaz.merhaba gönder, gecit.kabul bekle
 *   4. 10 Hz telemetri bas, gelen komutları uygula ve onayla
 */

import { WebSocket } from "ws";

const argv = process.argv.slice(2);
const arg = (ad) => {
  const i = argv.indexOf(`--${ad}`);
  return i >= 0 ? argv[i + 1] : undefined;
};

const SITE = arg("site") ?? process.env.SITE_URL ?? "http://localhost:3000";
const PROTOCOL_VERSION = "1";

let jeton = arg("jeton");
let gecitUrl = arg("gecit") ?? process.env.GECIT_URL ?? "ws://localhost:8420";

if (!jeton) {
  const kod = arg("kod");
  const seri = arg("seri");
  if (!kod || !seri) {
    console.error("Kullanım: --kod <eşleştirme kodu> --seri <seri no>  ya da  --jeton <jeton>");
    process.exit(1);
  }

  const yanit = await fetch(`${SITE}/api/cihaz/eslestir`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ kod, serial: seri, firmware: "sahte-1.0" }),
  });

  if (!yanit.ok) {
    console.error("Eşleştirme başarısız:", yanit.status, await yanit.text());
    process.exit(1);
  }

  const govde = await yanit.json();
  jeton = govde.token;
  gecitUrl = govde.gecitUrl;
  console.log("Eşleştirildi. Cihaz:", govde.cihazId);
  console.log("Jeton (saklayın):", jeton);
}

const soket = new WebSocket(`${gecitUrl.replace(/\/$/, "")}/ws/cihaz`);

/* ── Robotun taklit edilen durumu ── */
let hedefYaw = 0;
let gercekYaw = 0;
let eStop = false;
const HIZ_DEG_S = 90; // firmware hız rampasının kabaca karşılığı
const DEADBAND = 3 / 2.5882; // 3 tick

soket.on("open", () => {
  console.log("Ağ geçidine bağlanıldı, merhaba gönderiliyor…");
  soket.send(
    JSON.stringify({
      kind: "cihaz.merhaba",
      v: PROTOCOL_VERSION,
      token: jeton,
      firmware: "sahte-1.0",
    }),
  );
});

soket.on("message", (ham) => {
  const c = JSON.parse(ham.toString());

  if (c.kind === "gecit.kabul") {
    console.log("Kabul edildi. Cihaz:", c.cihazId, "sınır:", c.limits.headYawDeg);
    telemetriBasla();
    return;
  }

  if (c.kind === "gecit.ping") {
    soket.send(JSON.stringify({ kind: "cihaz.pong", t: c.t }));
    return;
  }

  if (c.kind === "gecit.komut") {
    const k = c.komut;
    let kabul = true;
    let neden;

    if (k.kind === "head.target") {
      if (eStop) {
        kabul = false;
        neden = "Acil durdurma etkin";
      } else {
        hedefYaw = k.yawDeg;
      }
    } else if (k.kind === "head.center") {
      if (eStop) {
        kabul = false;
        neden = "Acil durdurma etkin";
      } else {
        hedefYaw = 0;
      }
    } else if (k.kind === "estop") {
      eStop = k.engaged;
      if (eStop) hedefYaw = gercekYaw; // Durdurunca olduğu yerde kalır.
    }

    console.log(`komut: ${k.kind}`, kabul ? "kabul" : `RED (${neden})`);
    soket.send(JSON.stringify({ kind: "cihaz.onay", komutId: c.komutId, kabul, neden }));
    return;
  }

  if (c.kind === "gecit.hata") {
    console.error("ağ geçidi hatası:", c.kod, c.mesaj);
  }
});

soket.on("close", (kod, neden) => {
  console.log("Bağlantı kapandı:", kod, neden.toString());
  process.exit(0);
});

soket.on("error", (hata) => {
  console.error("Soket hatası:", hata.message);
  process.exit(1);
});

function telemetriBasla() {
  const ARALIK_MS = 100; // 10 Hz
  let t0 = Date.now();

  setInterval(() => {
    const simdi = Date.now();
    const dt = (simdi - t0) / 1000;
    t0 = simdi;

    // Ölü bant içindeyse hiç oynamaz — firmware davranışının taklidi.
    const fark = hedefYaw - gercekYaw;
    if (!eStop && Math.abs(fark) > DEADBAND) {
      const adim = Math.sign(fark) * Math.min(Math.abs(fark), HIZ_DEG_S * dt);
      gercekYaw += adim;
    }

    const konusuyor = Math.sin(simdi / 3000) > 0.3;

    soket.send(
      JSON.stringify({
        kind: "cihaz.telemetri",
        payload: {
          t: simdi,
          source: "robot",
          connected: true,
          head: {
            desiredYawDeg: Number(hedefYaw.toFixed(2)),
            actualYawDeg: Number(gercekYaw.toFixed(2)),
            encoderOk: true,
          },
          gaze: {
            attentionOwner: konusuyor ? "audio" : "none",
            visualValid: false,
            state: eStop ? "STOPPED" : konusuyor ? "ORIENTING" : "IDLE",
          },
          audio: {
            doaDeg: konusuyor ? Number((Math.sin(simdi / 5000) * 60).toFixed(1)) : null,
            confidence: konusuyor ? 0.82 : 0,
            vad: konusuyor,
          },
          faces: [],
          safety: { eStop, watchdogOk: true },
        },
      }),
    );
  }, ARALIK_MS);

  console.log("Telemetri akıyor (10 Hz). Durdurmak için Ctrl+C.");
}
