/**
 * ASTRO web — telemetri ve komut sözleşmesi.
 *
 * Bu dosya sunucu, istemci ve (faz 2'de) `astro_web` ROS köprüsü arasındaki TEK
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
 */

/** Dikkatin sahibi — /gaze/debug içindeki `attention_owner` alanının karşılığı. */
export type AttentionOwner = "visual" | "audio" | "none";

/** Telemetrinin nereden geldiği. Arayüzde her zaman görünür olmalıdır. */
export type TelemetrySource = "mock" | "robot";

export interface HeadTelemetry {
  /** Gaze döngüsünün istediği açı (derece, +sol / −sağ, base_link çerçevesi). */
  desiredYawDeg: number;
  /** Encoder'ın ölçtüğü gerçek açı. Geri besleme yoksa `encoderOk=false`. */
  actualYawDeg: number;
  /**
   * Encoder geri beslemesi akıyor mu. Akmıyorsa bütün kerterizler çöker —
   * bu bayrak arayüzde sessizce yutulmamalıdır.
   */
  encoderOk: boolean;
}

export interface GazeTelemetry {
  attentionOwner: AttentionOwner;
  visualValid: boolean;
  /** SocialGazeFSM durum adı (ör. "TRACKING", "SEARCHING"). */
  state: string;
}

export interface AudioTelemetry {
  /** Kafaya göre değil, gövdeye göre ses azimutu. Yön yoksa null. */
  doaDeg: number | null;
  /** 0..1 */
  confidence: number;
  /** Ses etkinliği algılandı mı. */
  vad: boolean;
}

export interface FaceObservation {
  /** Tanınmadıysa null. */
  name: string | null;
  /** 0..1 — eşiğin altındaki gözlem hiç geçerli sayılmaz. */
  confidence: number;
  /** Normalize edilmiş kare içi kutu: [x, y, w, h], her biri 0..1. */
  box: [number, number, number, number];
  /** Metre cinsinden derinlik; stereo yoksa null. */
  distanceM: number | null;
}

export interface SafetyTelemetry {
  eStop: boolean;
  /** Firmware heartbeat'i 500 ms içinde yenilendi mi. */
  watchdogOk: boolean;
}

export interface Telemetry {
  /** Köprünün damgaladığı zaman (ms, epoch). Gecikme ölçümü buna dayanır. */
  t: number;
  source: TelemetrySource;
  /** Köprü ile robot arasındaki bağlantı. `false` iken alanlar son bilinen değerdir. */
  connected: boolean;
  head: HeadTelemetry;
  gaze: GazeTelemetry;
  audio: AudioTelemetry;
  faces: FaceObservation[];
  safety: SafetyTelemetry;
}

/**
 * İstemciden gelen komutlar.
 *
 * Açı kırpması burada DEĞİL, köprüde yapılır: istemciye güvenilmez. İstemci
 * tarafındaki sınır yalnızca kullanıcıya geri bildirimdir.
 */
export type Command =
  | { kind: "head.target"; yawDeg: number }
  | { kind: "head.center" }
  | { kind: "estop"; engaged: boolean };

/** Sunucudan istemciye giden metin çerçeveleri. */
export type ServerMessage =
  | { kind: "telemetry"; payload: Telemetry }
  | { kind: "hello"; source: TelemetrySource; limits: { headYawDeg: number } }
  | { kind: "error"; message: string };
