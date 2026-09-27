/**
 * Jeton doğrulama.
 *
 * Birincil strateji: doğrudan PostgreSQL sorgusu.
 *   - Jetson üzerinde gateway ve DB yan yana çalışır.
 *   - Site (Next.js) ayakta olmasa da doğrulama çalışır.
 *   - DATABASE_URL ortam değişkeni tanımlıysa bu yol kullanılır.
 *
 * Yedek strateji: Next.js site API'sine HTTP çağrısı.
 *   - DB erişimi yoksa veya pg paketi yoksa devreye girer.
 *   - GATEWAY_SHARED_SECRET ile imzalı çağrı yapılır.
 */

import { createHash, createHmac, timingSafeEqual } from "node:crypto";

export interface CihazDogrulama {
  ok: true;
  cihazId: string;
  serial: string;
}

export interface PanelDogrulama {
  ok: true;
  cihazId: string;
  kullaniciId: string;
  komutVerebilir: boolean;
}

export type DogrulamaSonuc<T> = T | { ok: false; neden: string };

const SITE_URL = process.env.SITE_URL ?? "http://localhost:3000";
const GECIT_SIRRI = process.env.GATEWAY_SHARED_SECRET ?? "";
const DATABASE_URL = process.env.DATABASE_URL ?? "";

// --------------------------------------------------------------------------
// Yardımcılar
// --------------------------------------------------------------------------

function tokenOzetle(token: string): string {
  return createHash("sha256").update(token).digest("hex");
}

interface PanelJetonuIcerik {
  cihazId: string;
  kullaniciId: string;
  komutVerebilir: boolean;
  exp: number;
}

function panelJetonuCoz(jeton: string): PanelJetonuIcerik | null {
  const sir = process.env.BETTER_AUTH_SECRET;
  if (!sir) return null;
  const parts = jeton.split(".");
  if (parts.length < 2) return null;
  const govde = parts[0];
  const imza = parts[1];
  if (!govde || !imza) return null;
  const beklenen = createHmac("sha256", sir).update(govde).digest("base64url");
  const a = Buffer.from(imza);
  const b = Buffer.from(beklenen);
  if (a.length !== b.length || !timingSafeEqual(a, b)) return null;
  try {
    const icerik = JSON.parse(
      Buffer.from(govde, "base64url").toString(),
    ) as PanelJetonuIcerik;
    if (typeof icerik.exp !== "number" || icerik.exp < Date.now()) return null;
    return icerik;
  } catch {
    return null;
  }
}

// --------------------------------------------------------------------------
// Birincil yol: doğrudan PostgreSQL
// --------------------------------------------------------------------------

async function pgConnect(): Promise<import("pg").Client | null> {
  if (!DATABASE_URL) return null;
  try {
    const pg = await import("pg");
    const Client = (pg as unknown as { default: { Client: typeof import("pg").Client } }).default?.Client ?? pg.Client;
    const client = new Client({ connectionString: DATABASE_URL });
    await client.connect();
    return client;
  } catch {
    return null;
  }
}

async function dbdenCihazSor(
  token: string,
): Promise<{ ok: true; cihazId: string; serial: string } | { ok: false; neden: string } | null> {
  const client = await pgConnect();
  if (!client) return null; // pg yok ya da bağlanamadı → HTTP yoluna düş
  try {
    const hash = tokenOzetle(token);
    const res = await client.query(
      "SELECT id, serial FROM devices WHERE token_hash = $1 AND revoked_at IS NULL LIMIT 1",
      [hash],
    );
    if (res.rows.length === 0) {
      return { ok: false, neden: "Cihaz jetonu geçersiz ya da iptal edilmiş." };
    }
    const row = res.rows[0] as { id: string; serial: string };
    // Arka planda güncelle; hata olursa sessizce geç
    client
      .query(
        "UPDATE devices SET last_seen_at = NOW(), status = 'cevrimici' WHERE id = $1",
        [row.id],
      )
      .catch(() => {});
    return { ok: true, cihazId: row.id, serial: row.serial };
  } catch (err) {
    console.warn("[dogrula] DB sorgu hatası:", String(err));
    return null;
  } finally {
    client.end().catch(() => {});
  }
}

async function dbdenPanelSor(
  token: string,
): Promise<
  | { ok: true; cihazId: string; kullaniciId: string; komutVerebilir: boolean }
  | { ok: false; neden: string }
  | null
> {
  const icerik = panelJetonuCoz(token);
  if (!icerik) return { ok: false, neden: "Panel jetonu geçersiz ya da süresi geçmiş." };
  const client = await pgConnect();
  if (!client) return null;
  try {
    const res = await client.query(
      "SELECT id FROM devices WHERE id = $1 AND revoked_at IS NULL LIMIT 1",
      [icerik.cihazId],
    );
    if (res.rows.length === 0) {
      return { ok: false, neden: "Panel jetonu geçersiz ya da süresi geçmiş." };
    }
    return {
      ok: true,
      cihazId: icerik.cihazId,
      kullaniciId: icerik.kullaniciId,
      komutVerebilir: icerik.komutVerebilir,
    };
  } catch (err) {
    console.warn("[dogrula] DB sorgu hatası:", String(err));
    return null;
  } finally {
    client.end().catch(() => {});
  }
}

// --------------------------------------------------------------------------
// Yedek yol: HTTP
// --------------------------------------------------------------------------

async function siteyeSor(
  govde: Record<string, unknown>,
): Promise<Record<string, unknown> | null> {
  if (!GECIT_SIRRI) {
    throw new Error(
      "GATEWAY_SHARED_SECRET tanımlı değil; ağ geçidi jeton doğrulayamaz.",
    );
  }
  const yanit = await fetch(`${SITE_URL}/api/gecit/dogrula`, {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "x-gecit-sirri": GECIT_SIRRI,
    },
    body: JSON.stringify(govde),
    signal: AbortSignal.timeout(5000),
  });
  if (!yanit.ok) return null;
  return (await yanit.json()) as Record<string, unknown>;
}

// --------------------------------------------------------------------------
// Dışa açık fonksiyonlar
// --------------------------------------------------------------------------

export async function cihazDogrula(
  token: string,
): Promise<DogrulamaSonuc<CihazDogrulama>> {
  // 1️⃣ Doğrudan DB
  const dbSonuc = await dbdenCihazSor(token);
  if (dbSonuc !== null) return dbSonuc as DogrulamaSonuc<CihazDogrulama>;

  // 2️⃣ HTTP yolu (yedek)
  try {
    const yanit = await siteyeSor({ tur: "cihaz", token });
    if (!yanit || yanit.ok !== true) {
      return { ok: false, neden: "Cihaz jetonu geçersiz ya da iptal edilmiş." };
    }
    return {
      ok: true,
      cihazId: String(yanit.cihazId),
      serial: String(yanit.serial ?? ""),
    };
  } catch (hata) {
    return { ok: false, neden: `Doğrulama yapılamadı: ${String(hata)}` };
  }
}

export async function panelDogrula(
  token: string,
): Promise<DogrulamaSonuc<PanelDogrulama>> {
  // 1️⃣ Doğrudan DB + HMAC doğrulama
  const dbSonuc = await dbdenPanelSor(token);
  if (dbSonuc !== null) return dbSonuc as DogrulamaSonuc<PanelDogrulama>;

  // 2️⃣ HTTP yolu (yedek)
  try {
    const yanit = await siteyeSor({ tur: "panel", token });
    if (!yanit || yanit.ok !== true) {
      return { ok: false, neden: "Panel jetonu geçersiz ya da süresi geçmiş." };
    }
    return {
      ok: true,
      cihazId: String(yanit.cihazId),
      kullaniciId: String(yanit.kullaniciId),
      komutVerebilir: yanit.komutVerebilir === true,
    };
  } catch (hata) {
    return { ok: false, neden: `Doğrulama yapılamadı: ${String(hata)}` };
  }
}
