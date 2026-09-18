/**
 * Sahnenin çizmek için ihtiyaç duyduğu her şey.
 *
 * Sahne, verinin nereden geldiğini bilmez: giriş sayfasında senaryolu bir
 * sürücü, konsolda gerçek telemetri aynı yapıyı doldurur. Bu ayrım sayesinde
 * konsol ile giriş sayfası aynı sahneyi paylaşır, iki kopya bakılmaz.
 */
export interface SceneState {
  /** Kafanın o anki açısı (derece, +sol / −sağ). */
  headYawDeg: number;
  /** Sesin geldiği yön (derece, gövdeye göre). Yön yoksa null. */
  doaDeg: number | null;
  /** Ses etkinliği var mı — yön işaretinin parlaklığını sürer. */
  vad: boolean;
  /** Görüş alanında geçerli bir yüz var mı — koninin rengini sürer. */
  faceVisible: boolean;
}

export const IDLE_STATE: SceneState = {
  headYawDeg: 0,
  doaDeg: null,
  vad: false,
  faceVisible: false,
};

/** Zamanla `SceneState` üreten kaynak. */
export interface SceneDriver {
  /** @param dt saniye cinsinden geçen süre. */
  update(dt: number): SceneState;
}
