import fastifyWebsocket from "@fastify/websocket";
import Fastify from "fastify";

import { HEAD_YAW_LIMIT_DEG, PROTOCOL_VERSION } from "@astro/protocol";
import { cihazCerceveSchema, panelCerceveSchema } from "@astro/protocol/wire";

import { cihazDogrula, panelDogrula } from "./dogrula";
import { HizSiniri } from "./hiz-siniri";
import { KayitDefteri, type CihazBaglantisi, type PanelBaglantisi } from "./kayit-defteri";
import { surumUyumlu } from "./surum";

const PORT = Number(process.env.PORT ?? 8420);
const HOST = process.env.HOST ?? "0.0.0.0";

/** Komut hız sınırı: panel başına saniyede 20. */
const KOMUT_LIMIT = Number(process.env.KOMUT_LIMIT ?? 20);
const KOMUT_PENCERE_MS = 1000;

/** Sessiz kalan bağlantı bu süreden sonra kapatılır. */
const SESSIZLIK_ESIGI_MS = 30_000;
const PING_ARALIGI_MS = 5_000;

const defter = new KayitDefteri();
const app = Fastify({ logger: { level: process.env.LOG_LEVEL ?? "info" } });

await app.register(fastifyWebsocket);

app.get("/saglik", async () => ({
  ok: true,
  v: PROTOCOL_VERSION,
  ...defter.ozet(),
}));

/* ────────────────────────────  Robot ajanı ucu  ───────────────────────── */

/**
 * Robot buraya **dışa doğru** bağlanır.
 *
 * Müşteri ağında port açılmaz, yönlendirme yapılmaz. İlk çerçeve
 * `cihaz.merhaba` olmak zorunda; jeton doğrulanana kadar başka hiçbir çerçeve
 * işlenmez.
 */
app.get("/ws/cihaz", { websocket: true }, (socket) => {
  let baglanti: CihazBaglantisi | null = null;
  let sonSes = Date.now();

  const hata = (kod: string, mesaj: string): void => {
    socket.send(JSON.stringify({ kind: "gecit.hata", kod, mesaj }));
  };

  const nabiz = setInterval(() => {
    if (Date.now() - sonSes > SESSIZLIK_ESIGI_MS) {
      socket.close(4002, "Sessiz kalındı");
      return;
    }
    socket.send(JSON.stringify({ kind: "gecit.ping", t: Date.now() }));
  }, PING_ARALIGI_MS);

  socket.on("message", (ham: Buffer) => {
    sonSes = Date.now();

    let govde: unknown;
    try {
      govde = JSON.parse(ham.toString());
    } catch {
      hata("sozlesme-disi", "Çerçeve çözümlenemedi");
      return;
    }

    const cozulmus = cihazCerceveSchema.safeParse(govde);
    if (!cozulmus.success) {
      /*
       * Robot da istemci kadar şüpheli: jetonu ele geçirilmiş bir ajan bozuk
       * telemetri basabilir ve panel onu gerçek sanardı.
       */
      hata("sozlesme-disi", "Çerçeve sözleşmeye uymuyor");
      return;
    }

    const cerceve = cozulmus.data;

    if (cerceve.kind === "cihaz.merhaba") {
      if (baglanti) return; // İkinci merhaba yok sayılır.

      if (!surumUyumlu(cerceve.v)) {
        hata("surum-uyusmazligi", `Ağ geçidi sözleşme sürümü ${PROTOCOL_VERSION}`);
        socket.close(4003, "Sürüm uyuşmazlığı");
        return;
      }

      void (async () => {
        const sonuc = await cihazDogrula(cerceve.token);
        if (!sonuc.ok) {
          hata("jeton-gecersiz", sonuc.neden);
          socket.close(4001, "Jeton geçersiz");
          return;
        }

        baglanti = {
          cihazId: sonuc.cihazId,
          firmware: cerceve.firmware ?? null,
          baglandi: Date.now(),
          sonGorulme: Date.now(),
          gonder: (c) => socket.send(JSON.stringify(c)),
          kapat: (kod, neden) => socket.close(kod, neden),
        };

        defter.cihazBagla(baglanti);
        app.log.info({ cihazId: sonuc.cihazId }, "cihaz bağlandı");

        socket.send(
          JSON.stringify({
            kind: "gecit.kabul",
            v: PROTOCOL_VERSION,
            cihazId: sonuc.cihazId,
            limits: { headYawDeg: HEAD_YAW_LIMIT_DEG },
          }),
        );
      })();
      return;
    }

    // Merhaba gelmeden başka çerçeve işlenmez.
    if (!baglanti) {
      hata("jeton-gecersiz", "Önce cihaz.merhaba gönderin");
      return;
    }

    if (cerceve.kind === "cihaz.telemetri") {
      defter.telemetriDagit(baglanti.cihazId, cerceve.payload);
      return;
    }

    if (cerceve.kind === "cihaz.onay") {
      defter.panellereYolla(baglanti.cihazId, {
        kind: "gecit.onay",
        komutId: cerceve.komutId,
        kabul: cerceve.kabul,
        neden: cerceve.neden,
      });
      return;
    }

    // cihaz.pong: nabız zaten `sonSes` ile güncellendi.
  });

  socket.on("close", () => {
    clearInterval(nabiz);
    if (baglanti) {
      defter.cihazAyril(baglanti.cihazId, baglanti);
      app.log.info({ cihazId: baglanti.cihazId }, "cihaz ayrıldı");
    }
  });
});

/* ──────────────────────────────  Panel ucu  ───────────────────────────── */

app.get("/ws/panel", { websocket: true }, (socket) => {
  let panel: PanelBaglantisi | null = null;
  const limit = new HizSiniri(KOMUT_LIMIT, KOMUT_PENCERE_MS);
  let sonSes = Date.now();

  const hata = (kod: string, mesaj: string): void => {
    socket.send(JSON.stringify({ kind: "gecit.hata", kod, mesaj }));
  };

  const nabiz = setInterval(() => {
    if (Date.now() - sonSes > SESSIZLIK_ESIGI_MS) {
      socket.close(4002, "Sessiz kalındı");
      return;
    }
    socket.send(JSON.stringify({ kind: "gecit.ping", t: Date.now() }));
  }, PING_ARALIGI_MS);

  socket.on("message", (ham: Buffer) => {
    sonSes = Date.now();

    let govde: unknown;
    try {
      govde = JSON.parse(ham.toString());
    } catch {
      hata("sozlesme-disi", "Çerçeve çözümlenemedi");
      return;
    }

    const cozulmus = panelCerceveSchema.safeParse(govde);
    if (!cozulmus.success) {
      hata("sozlesme-disi", "Çerçeve sözleşmeye uymuyor");
      return;
    }

    const cerceve = cozulmus.data;

    if (cerceve.kind === "panel.merhaba") {
      if (panel) return;

      if (!surumUyumlu(cerceve.v)) {
        hata("surum-uyusmazligi", `Ağ geçidi sözleşme sürümü ${PROTOCOL_VERSION}`);
        socket.close(4003, "Sürüm uyuşmazlığı");
        return;
      }

      void (async () => {
        const sonuc = await panelDogrula(cerceve.token);
        if (!sonuc.ok) {
          hata("jeton-gecersiz", sonuc.neden);
          socket.close(4001, "Jeton geçersiz");
          return;
        }

        panel = {
          cihazId: sonuc.cihazId,
          kullaniciId: sonuc.kullaniciId,
          komutVerebilir: sonuc.komutVerebilir,
          gonder: (c) => socket.send(JSON.stringify(c)),
        };

        socket.send(
          JSON.stringify({
            kind: "gecit.panel-kabul",
            v: PROTOCOL_VERSION,
            cihazId: sonuc.cihazId,
            komutVerebilir: sonuc.komutVerebilir,
            limits: { headYawDeg: HEAD_YAW_LIMIT_DEG },
          }),
        );

        defter.panelBagla(panel);
      })();
      return;
    }

    if (!panel) {
      hata("jeton-gecersiz", "Önce panel.merhaba gönderin");
      return;
    }

    if (cerceve.kind === "panel.komut") {
      if (!panel.komutVerebilir) {
        // İzleyici yalnızca bakar. Arayüz düğmeyi zaten çizmiyor ama soket
        // doğrudan da kullanılabilir.
        hata("yetki-yok", "Bu cihazda komut verme yetkiniz yok");
        return;
      }

      if (!limit.izinVer()) {
        hata("hiz-siniri", `Saniyede en fazla ${KOMUT_LIMIT} komut`);
        return;
      }

      const cihaz = defter.cihazAl(panel.cihazId);
      if (!cihaz) {
        /*
         * Robot bağlı değilken komut kuyruğa alınmıyor. Sonradan teslim edilen
         * bir hareket komutu, operatörün artık istemediği bir hareketi
         * yaptırabilir.
         */
        socket.send(
          JSON.stringify({
            kind: "gecit.onay",
            komutId: cerceve.komutId,
            kabul: false,
            neden: "Robot bağlı değil",
          }),
        );
        return;
      }

      cihaz.gonder({
        kind: "gecit.komut",
        komutId: cerceve.komutId,
        komut: cerceve.komut,
      });

      app.log.info(
        {
          cihazId: panel.cihazId,
          kullaniciId: panel.kullaniciId,
          komut: cerceve.komut.kind,
          komutId: cerceve.komutId,
        },
        "komut iletildi",
      );
      return;
    }

    // panel.pong: nabız `sonSes` ile güncellendi.
  });

  socket.on("close", () => {
    clearInterval(nabiz);
    if (panel) defter.panelAyril(panel);
  });
});

const kapat = async (): Promise<void> => {
  await app.close();
  process.exit(0);
};
process.on("SIGINT", kapat);
process.on("SIGTERM", kapat);

await app.listen({ port: PORT, host: HOST });
app.log.info({ v: PROTOCOL_VERSION }, `ağ geçidi hazır — /ws/cihaz ve /ws/panel`);
