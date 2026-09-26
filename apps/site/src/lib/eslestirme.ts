import { createHash, randomBytes } from "node:crypto";

/**
 * Cihaz eşleştirme kodu.
 *
 * Kod kullanıcıya bir kez gösterilir; veritabanında yalnızca özeti durur.
 * Veritabanı sızsa bile kodlarla cihaz bağlanamaz.
 *
 * Alfabede karışan karakterler yok (0/O, 1/I/l): kod elle ya da sesli olarak
 * aktarılacak ve yanlış okunan bir karakter kullanıcıya "kod geçersiz" demekten
 * başka bir şey söylemiyor.
 */
const ALFABE = "ABCDEFGHJKMNPQRSTUVWXYZ23456789";
const GRUP = 4;
const GRUP_SAYISI = 4;

export function eslestirmeKoduUret(): string {
  const bayt = randomBytes(GRUP * GRUP_SAYISI);
  const harfler = Array.from(bayt, (b) => ALFABE[b % ALFABE.length]).join("");
  const gruplar: string[] = [];
  for (let i = 0; i < GRUP_SAYISI; i++) {
    gruplar.push(harfler.slice(i * GRUP, (i + 1) * GRUP));
  }
  return gruplar.join("-");
}

/**
 * Kodun özeti.
 *
 * Parola değil, yüksek entropili ve kısa ömürlü bir kod olduğu için SHA-256
 * yeterli: bcrypt/argon2 yavaşlığının koruduğu şey düşük entropili parolalara
 * karşı sözlük saldırısı ve burada öyle bir risk yok.
 */
export function koduOzetle(kod: string): string {
  return createHash("sha256").update(kod.trim().toUpperCase()).digest("hex");
}

/** Kod ömrü: 24 saat. Süresi geçen kod yeniden üretilebilir. */
export const ESLESTIRME_OMRU_MS = 24 * 60 * 60 * 1000;
