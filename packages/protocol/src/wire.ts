/**
 * Ağ geçidi tel sözleşmesi — robot ajanı ve tarayıcı paneli için.
 *
 * İki ayrı soket vardır ve ikisi de farklı çerçeveler konuşur:
 *
 *   robot ajanı  ──wss://gw/ws/cihaz──>  ağ geçidi  <──wss://gw/ws/panel── tarayıcı
 *
 * Robot **dışa doğru** bağlanır. Müşteri ağında port açılmaz, yönlendirme
 * yapılmaz; bağlantıyı robot kurar ve ağ geçidi yalnızca kabul eder.
 *
 * Bütün çerçeveler burada tanımlı ve zod ile doğrulanır. Ağ geçidi her iki
 * taraftan geleni de doğrular: robot da istemci kadar şüphelidir, çünkü
 * jetonu çalınmış bir ajan bozuk telemetri basabilir.
 */

import { z } from "zod";

import { HEAD_YAW_LIMIT_DEG } from "./limits";
import { commandSchema, telemetrySchema } from "./schema";
import { PROTOCOL_VERSION } from "./version";

/* ───────────────────────────  Robot ajanı → ağ geçidi  ─────────────────── */

export const cihazMerhabaSchema = z.object({
  kind: z.literal("cihaz.merhaba"),
  /** Ana sürüm uyuşmazsa bağlantı reddedilir. */
  v: z.string(),
  /** Eşleştirme sonrası alınan uzun ömürlü jeton. */
  token: z.string().min(16).max(512),
  firmware: z.string().max(64).optional(),
});

/**
 * Komut sonucu.
 *
 * Operatör komutu gönderdiğinde uygulandığını görmeli. Onaysız bir komut yolu,
 * "gönderdim ama oldu mu?" sorusunu cevaplayamıyor.
 */
export const cihazOnaySchema = z.object({
  kind: z.literal("cihaz.onay"),
  /** Karşılık geldiği komutun kimliği. */
  komutId: z.string().max(64),
  kabul: z.boolean(),
  /** Reddedildiyse nedeni. */
  neden: z.string().max(200).optional(),
});

export const cihazTelemetriSchema = z.object({
  kind: z.literal("cihaz.telemetri"),
  payload: telemetrySchema,
});

/** Gecikme ölçümünün robot bacağı. */
export const cihazPongSchema = z.object({
  kind: z.literal("cihaz.pong"),
  /** Ağ geçidinin gönderdiği damga, olduğu gibi geri döner. */
  t: z.number(),
});

export const cihazCerceveSchema = z.discriminatedUnion("kind", [
  cihazMerhabaSchema,
  cihazTelemetriSchema,
  cihazOnaySchema,
  cihazPongSchema,
]);

/* ───────────────────────────  Ağ geçidi → robot ajanı  ─────────────────── */

export const gecitKomutSchema = z.object({
  kind: z.literal("gecit.komut"),
  /** Onayın hangi komuda ait olduğunu bilmek için. */
  komutId: z.string().max(64),
  komut: commandSchema,
});

export const gecitPingSchema = z.object({
  kind: z.literal("gecit.ping"),
  t: z.number(),
});

export const gecitKabulSchema = z.object({
  kind: z.literal("gecit.kabul"),
  v: z.string(),
  cihazId: z.string(),
  limits: z.object({ headYawDeg: z.number() }),
});

export const gecitHataSchema = z.object({
  kind: z.literal("gecit.hata"),
  kod: z.enum([
    "surum-uyusmazligi",
    "jeton-gecersiz",
    "sozlesme-disi",
    "hiz-siniri",
    "yetki-yok",
    "cihaz-bagli-degil",
  ]),
  mesaj: z.string().max(300),
});

export const gecitCerceveSchema = z.discriminatedUnion("kind", [
  gecitKabulSchema,
  gecitKomutSchema,
  gecitPingSchema,
  gecitHataSchema,
]);

/* ─────────────────────────────  Tarayıcı ↔ ağ geçidi  ──────────────────── */

export const panelMerhabaSchema = z.object({
  kind: z.literal("panel.merhaba"),
  v: z.string(),
  /** Sitenin bastığı kısa ömürlü jeton. */
  token: z.string().min(16).max(2048),
});

export const panelKomutSchema = z.object({
  kind: z.literal("panel.komut"),
  komutId: z.string().max(64),
  komut: commandSchema,
});

export const panelPongSchema = z.object({
  kind: z.literal("panel.pong"),
  t: z.number(),
});

export const panelCerceveSchema = z.discriminatedUnion("kind", [
  panelMerhabaSchema,
  panelKomutSchema,
  panelPongSchema,
]);

/**
 * Cihazın bağlantı durumu.
 *
 * Panelde her zaman görünür olmalı: bağlantı yokken son bilinen değeri canlı
 * gibi göstermek, operatöre olmayan bir robotu yönettiğini düşündürür.
 */
export const gecitCihazDurumSchema = z.object({
  kind: z.literal("gecit.cihaz-durum"),
  bagli: z.boolean(),
  /** Robotun son görüldüğü an (ms, epoch). Hiç bağlanmadıysa null. */
  sonGorulme: z.number().nullable(),
  firmware: z.string().nullable(),
});

export const gecitTelemetriSchema = z.object({
  kind: z.literal("gecit.telemetri"),
  payload: telemetrySchema,
  /** Ağ geçidinin çerçeveyi ilettiği an; gecikme hesabı buna dayanır. */
  t: z.number(),
});

export const gecitOnaySchema = z.object({
  kind: z.literal("gecit.onay"),
  komutId: z.string().max(64),
  kabul: z.boolean(),
  neden: z.string().max(200).optional(),
});

export const gecitPanelKabulSchema = z.object({
  kind: z.literal("gecit.panel-kabul"),
  v: z.string(),
  cihazId: z.string(),
  /** İzleyici komut gönderemez; arayüz buna göre çizilir. */
  komutVerebilir: z.boolean(),
  limits: z.object({ headYawDeg: z.number() }),
});

export const gecitPanelCerceveSchema = z.discriminatedUnion("kind", [
  gecitPanelKabulSchema,
  gecitCihazDurumSchema,
  gecitTelemetriSchema,
  gecitOnaySchema,
  gecitPingSchema,
  gecitHataSchema,
]);

/* ─────────────────────────────  Eşleştirme (HTTP)  ─────────────────────── */

/**
 * Robot ajanının eşleştirme isteği.
 *
 * Ağ geçidine değil **siteye** gider: cihaz kayıtları sitenin veritabanında ve
 * ağ geçidi bilerek durumsuz. Karşılığında uzun ömürlü jeton alınır.
 */
export const eslestirmeIstegiSchema = z.object({
  kod: z.string().min(8).max(32),
  serial: z.string().min(4).max(64),
  firmware: z.string().max(64).optional(),
});

export const eslestirmeYanitiSchema = z.object({
  ok: z.literal(true),
  cihazId: z.string(),
  token: z.string(),
  /** Ajanın bağlanacağı adres; site söyler, ajan gömmez. */
  gecitUrl: z.string(),
  v: z.string(),
});

export type CihazCerceve = z.infer<typeof cihazCerceveSchema>;
export type GecitCerceve = z.infer<typeof gecitCerceveSchema>;
export type PanelCerceve = z.infer<typeof panelCerceveSchema>;
export type GecitPanelCerceve = z.infer<typeof gecitPanelCerceveSchema>;
export type EslestirmeIstegi = z.infer<typeof eslestirmeIstegiSchema>;
export type EslestirmeYaniti = z.infer<typeof eslestirmeYanitiSchema>;

/** Kafa açısı sınırı, tel sözleşmesinde de aynı kaynaktan. */
export const TEL_HEAD_YAW_LIMIT_DEG = HEAD_YAW_LIMIT_DEG;
export { PROTOCOL_VERSION };
