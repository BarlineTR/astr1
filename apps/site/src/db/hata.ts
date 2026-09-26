/**
 * Postgres hata kodlarını tanır.
 *
 * Drizzle hatayı `DrizzleQueryError` içine sarıyor ve `String(hata)` yalnızca
 * "Failed query: insert into ..." veriyor; özgün mesaj `cause` zincirinde
 * kalıyor. Metne bakan bir kontrol bu yüzden sessizce ıskalıyordu ve tekil
 * kısıt ihlali kullanıcıya anlaşılır bir hata yerine 500 olarak dönüyordu.
 *
 * Kod ile eşleştirmek ayrıca dile ve sürüme bağlı değil.
 */

/** Tekil kısıt ihlali. */
const TEKIL_IHLAL = "23505";

interface PgHata {
  code?: unknown;
  constraint?: unknown;
  cause?: unknown;
}

/** Hata zincirinde Postgres hata nesnesini arar. */
function pgHatasiBul(hata: unknown, derinlik = 0): PgHata | null {
  if (derinlik > 5 || hata === null || typeof hata !== "object") return null;
  const aday = hata as PgHata;
  if (typeof aday.code === "string") return aday;
  return pgHatasiBul(aday.cause, derinlik + 1);
}

/**
 * Verilen kısıt için tekil ihlal mi.
 *
 * @param kisit Kısıt adı verilirse yalnızca o kısıt için doğru döner; başka bir
 *              tekil kısıt ihlalini yanlışlıkla aynı hata sanmamak için.
 */
export function tekilIhlalMi(hata: unknown, kisit?: string): boolean {
  const pg = pgHatasiBul(hata);
  if (!pg || pg.code !== TEKIL_IHLAL) return false;
  if (!kisit) return true;
  return pg.constraint === kisit;
}
