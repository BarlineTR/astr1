/**
 * Fiziksel sınırlar. Kaynak: `ros2_ws/src/astro_base/config/calibration_params.yaml`
 * ve `docs/hardware.md §4`.
 *
 * Bu değerler üç yerde birden zorlanır — arayüz kaydırıcısı, köprü kırpması ve
 * firmware. Buradaki kopya yalnızca arayüzün doğru aralığı çizmesi içindir;
 * güvenliği sağlayan katman firmware'dir.
 */

/**
 * Yazılım güvenli aralığı. Firmware ±180 kabul eder ve mekanik sert durdurucular
 * ±90°'nin ötesindedir, ama encoder yalnızca 440 tick / 170° ile karakterize
 * edildi — ölçülmemiş aralığa çıkılmaz.
 */
export const HEAD_YAW_LIMIT_DEG = 85;

/** Encoder ölçek çarpanı: 440 tick / 170°. */
export const ENCODER_TICKS_PER_DEG = 2.5882;

/** Firmware deadband'i 3 tick; dişli boşluğu 0.85°. */
export const HEAD_DEADBAND_DEG = 3 / ENCODER_TICKS_PER_DEG;

/** OAK-D Lite yatay görüş açısı (derece). */
export const CAMERA_HFOV_DEG = 72;

/** OAK-D Lite dikey görüş açısı (derece). */
export const CAMERA_VFOV_DEG = 53;

/** Anında geçen sohbet konisi. */
export const AUDIO_CHAT_CONE_DEG = 75;

/** Kadraja girebilecek en geniş açı: kafa limiti 85 + kamera yarı-FOV 36. */
export const AUDIO_REACHABLE_DEG = 121;
