/**
 * ASTRO — telemetri ve komut sözleşmesi.
 *
 * Bu dosya sunucu, istemci ve (faz 4'te) `astro_web` ROS köprüsü arasındaki TEK
 * anlaşmadır. Alanların hepsi gerçek ROS topic'lerinden türetilmiştir; hiçbiri
 * gösterim için uydurulmamıştır:
 *
 *   head.*    ← /head/state        (astro_base_msgs/HeadState, encoder gerçeği)
 *             ← /head/cmd_pos      (std_msgs/Float32, gönderilen hedef)
 *   gaze.*    ← /gaze/debug        (std_msgs/String, JSON gövde)
 *   audio.*   ← /audio/doa_deg, /audio/doa_confidence, /audio/vad
 *   faces[]   ← /vision/faces      (std_msgs/String, JSON gövde)
 *   person    ← /vision/recognized_person
 *   safety.*  ← /safety/emergency_stop
 *
 * Kare görüntüsü bu sözleşmenin dışındadır: ayrı bir ikili WebSocket çerçevesinde
 * JPEG olarak taşınır (ham 900 KB'lık görüntü web'e olduğu gibi taşınamaz).
 *
 * Şemalar tip değil **zod** olarak yazılıdır, çünkü ağ geçidi istemciden geleni
 * çalışma zamanında doğrulamak zorundadır ve tipler orada hiçbir şey yapmaz.
 * Tipler şemadan türetilir; iki kopya tutulmaz.
 */

import { z } from "zod";

import { HEAD_YAW_LIMIT_DEG } from "./limits";

export { PROTOCOL_VERSION } from "./version";

/** Dikkatin sahibi — /gaze/debug içindeki `attention_owner` alanının karşılığı. */
export const attentionOwnerSchema = z.enum(["visual", "audio", "none"]);

/** Telemetrinin nereden geldiği. Arayüzde her zaman görünür olmalıdır. */
export const telemetrySourceSchema = z.enum(["mock", "robot"]);

export const headTelemetrySchema = z.object({
  /** Gaze döngüsünün istediği açı (derece, +sol / −sağ, base_link çerçevesi). */
  desiredYawDeg: z.number(),
  /** Encoder'ın ölçtüğü gerçek açı. Geri besleme yoksa `encoderOk=false`. */
  actualYawDeg: z.number(),
  /**
   * Encoder geri beslemesi akıyor mu. Akmıyorsa bütün kerterizler çöker —
   * bu bayrak arayüzde sessizce yutulmamalıdır.
   */
  encoderOk: z.boolean(),
});

export const gazeTelemetrySchema = z.object({
  attentionOwner: attentionOwnerSchema,
  visualValid: z.boolean(),
  /** SocialGazeFSM durum adı (ör. "TRACKING", "SEARCHING"). */
  state: z.string(),
});

export const audioTelemetrySchema = z.object({
  /** Kafaya göre değil, gövdeye göre ses azimutu. Yön yoksa null. */
  doaDeg: z.number().nullable(),
  /** 0..1 */
  confidence: z.number().min(0).max(1),
  /** Ses etkinliği algılandı mı. */
  vad: z.boolean(),
});

export const faceObservationSchema = z.object({
  /** Tanınmadıysa null. */
  name: z.string().nullable(),
  /** 0..1 — eşiğin altındaki gözlem hiç geçerli sayılmaz. */
  confidence: z.number().min(0).max(1),
  /** Normalize edilmiş kare içi kutu: [x, y, w, h], her biri 0..1. */
  box: z.tuple([z.number(), z.number(), z.number(), z.number()]),
  /** Metre cinsinden derinlik; stereo yoksa null. */
  distanceM: z.number().nullable(),
});

export const safetyTelemetrySchema = z.object({
  eStop: z.boolean(),
  /** Firmware heartbeat'i 500 ms içinde yenilendi mi. */
  watchdogOk: z.boolean(),
});

export const telemetrySchema = z.object({
  /** Köprünün damgaladığı zaman (ms, epoch). Gecikme ölçümü buna dayanır. */
  t: z.number(),
  source: telemetrySourceSchema,
  /** Köprü ile robot arasındaki bağlantı. `false` iken alanlar son bilinen değerdir. */
  connected: z.boolean(),
  head: headTelemetrySchema,
  gaze: gazeTelemetrySchema,
  audio: audioTelemetrySchema,
  faces: z.array(faceObservationSchema),
  safety: safetyTelemetrySchema,
});

/**
 * İstemciden gelen komutlar.
 *
 * Açı kırpması esas olarak köprüde yapılır: istemciye güvenilmez. Buradaki
 * sınır ikinci katmandır ve ikisi de ucuz olduğu için ikisi de duruyor.
 *
 * Sınır ihlali "kırpılarak kabul" edilmez, reddedilir — sessizce kırpmak
 * operatöre gönderdiği komutun uygulandığını düşündürür.
 */
export const commandSchema = z.discriminatedUnion("kind", [
  z.object({
    kind: z.literal("head.target"),
    yawDeg: z.number().min(-HEAD_YAW_LIMIT_DEG).max(HEAD_YAW_LIMIT_DEG),
  }),
  z.object({ kind: z.literal("head.center") }),
  z.object({ kind: z.literal("estop"), engaged: z.boolean() }),
]);

/** Sunucudan istemciye giden metin çerçeveleri. */
export const serverMessageSchema = z.discriminatedUnion("kind", [
  z.object({ kind: z.literal("telemetry"), payload: telemetrySchema }),
  z.object({
    kind: z.literal("hello"),
    /** Sözleşme sürümü. Ana sürüm uyuşmazsa bağlantı reddedilir. */
    v: z.string(),
    source: telemetrySourceSchema,
    limits: z.object({ headYawDeg: z.number() }),
  }),
  z.object({ kind: z.literal("error"), message: z.string() }),
]);

export type AttentionOwner = z.infer<typeof attentionOwnerSchema>;
export type TelemetrySource = z.infer<typeof telemetrySourceSchema>;
export type HeadTelemetry = z.infer<typeof headTelemetrySchema>;
export type GazeTelemetry = z.infer<typeof gazeTelemetrySchema>;
export type AudioTelemetry = z.infer<typeof audioTelemetrySchema>;
export type FaceObservation = z.infer<typeof faceObservationSchema>;
export type SafetyTelemetry = z.infer<typeof safetyTelemetrySchema>;
export type Telemetry = z.infer<typeof telemetrySchema>;
export type Command = z.infer<typeof commandSchema>;
export type ServerMessage = z.infer<typeof serverMessageSchema>;
