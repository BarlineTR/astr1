import { drizzle } from "drizzle-orm/node-postgres";
import { Pool } from "pg";

import * as schema from "./schema";

/**
 * Veritabanı istemcisi.
 *
 * `node-postgres` sürücüsü kullanılıyor, sağlayıcıya özgü bir sürücü değil:
 * aynı kod yönetilen Postgres'te de tek VPS'teki Docker Postgres'te de çalışır
 * (tasarım belgesi D4 — şimdi Vercel, sonra taşınabilir).
 *
 * Havuz modül kapsamında bir kez kurulur. Next geliştirme kipinde modülleri
 * sıcak yeniden yüklediği için globalThis üzerinde saklanır; yoksa her
 * yeniden yüklemede yeni bir havuz açılıp bağlantılar tükeniyor.
 */
const baglantiAdresi = process.env.DATABASE_URL;
if (!baglantiAdresi) {
  throw new Error(
    "DATABASE_URL tanımlı değil. Yerelde: docker compose -f docker/compose.yaml up -d " +
      "ve .env.local içinde DATABASE_URL ayarlayın (.env.example'a bakın).",
  );
}

const global_ = globalThis as unknown as { __astroPool?: Pool };

const pool =
  global_.__astroPool ??
  new Pool({
    connectionString: baglantiAdresi,
    max: 10,
  });

if (process.env.NODE_ENV !== "production") global_.__astroPool = pool;

export const db = drizzle(pool, { schema });
export { schema };
