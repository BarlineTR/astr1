import { createHash, createHmac, randomBytes, timingSafeEqual } from "node:crypto";

/**
 * Cihaz ve panel jetonları.
 *
 * İki ayrı jeton var ve ömürleri bilerek çok farklı:
 *
 *  - **Cihaz jetonu**: robot ajanı eşleştirme sonrası alır, uzun ömürlü.
 *    Rastgele ve veritabanında yalnızca özeti durur.
 *  - **Panel jetonu**: tarayıcı konsolu açtığında site basar, 60 saniyelik.
 *    Tabloya yazılmaz; HMAC ile imzalanır ve site kendi imzasını doğrular.
 *    Kısa ömürlü bir kayıt için tablo tutmak, temizlenmesi gereken bir çöp
 *    yığını demekti.
 */

const CIHAZ_JETON_BAYT = 32;

/** Panel jetonu ömrü. Bağlantı kurulumu için; kurulan bağlantı dolunca kopmaz. */
export const PANEL_JETON_OMRU_MS = 60_000;

export function cihazJetonuUret(): string {
  return randomBytes(CIHAZ_JETON_BAYT).toString("base64url");
}

/**
 * Cihaz jetonunun özeti.
 *
 * SHA-256 yeterli: jeton 32 rastgele bayt, yani düşük entropili parolalara
 * karşı koruyan yavaş özetlemenin (bcrypt/argon2) burada karşılığı yok.
 */
export function cihazJetonuOzetle(jeton: string): string {
  return createHash("sha256").update(jeton).digest("hex");
}

function sirriAl(): string {
  const sir = process.env.BETTER_AUTH_SECRET;
  if (!sir) {
    throw new Error("BETTER_AUTH_SECRET tanımlı değil; panel jetonu imzalanamaz.");
  }
  return sir;
}

export interface PanelJetonuIcerik {
  cihazId: string;
  kullaniciId: string;
  komutVerebilir: boolean;
  /** Son geçerlilik (ms, epoch). */
  exp: number;
}

/** İmzalı panel jetonu: `<base64url(json)>.<base64url(hmac)>`. */
export function panelJetonuImzala(icerik: PanelJetonuIcerik): string {
  const govde = Buffer.from(JSON.stringify(icerik)).toString("base64url");
  const imza = createHmac("sha256", sirriAl()).update(govde).digest("base64url");
  return `${govde}.${imza}`;
}

export function panelJetonuCoz(jeton: string): PanelJetonuIcerik | null {
  const [govde, imza] = jeton.split(".");
  if (!govde || !imza) return null;

  const beklenen = createHmac("sha256", sirriAl()).update(govde).digest("base64url");

  /*
   * Sabit zamanlı karşılaştırma: uzunluk farklıysa timingSafeEqual fırlatıyor,
   * o yüzden önce uzunluk kontrolü — o da zaten imza geçersiz demek.
   */
  const a = Buffer.from(imza);
  const b = Buffer.from(beklenen);
  if (a.length !== b.length || !timingSafeEqual(a, b)) return null;

  let icerik: PanelJetonuIcerik;
  try {
    icerik = JSON.parse(Buffer.from(govde, "base64url").toString()) as PanelJetonuIcerik;
  } catch {
    return null;
  }

  if (typeof icerik.exp !== "number" || icerik.exp < Date.now()) return null;
  return icerik;
}
