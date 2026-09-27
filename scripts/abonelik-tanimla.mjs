#!/usr/bin/env node
/**
 * ASTRO — Veritabanı üzerinden doğrudan e-posta ile abonelik ve hesap tanımlama aracı.
 *
 * Kullanım:
 *   node scripts/abonelik-tanimla.mjs <eposta> <planSlug> [sureGun] [--ad "Ad Soyad"] [--sifre "Parola"]
 *
 * Örnek:
 *   node scripts/abonelik-tanimla.mjs musteri@firma.com operasyon 365 --ad "Ahmet Yılmaz"
 *
 * Eğer kullanıcı veritabanında yoksa:
 *   - Hesabı otomatik oluşturur (e-posta onaylı).
 *   - Güvenli bir geçici şifre üretir (veya verilen şifreyi atar).
 *   - Aboneliği hemen tanımlar.
 *   - Müşteriye verilecek giriş bilgilerini ekrana basar.
 */
import fs from "node:fs";
import path from "node:path";
import pg from "pg";
import { randomBytes, randomUUID } from "node:crypto";

function loadEnvFile(envPath) {
  if (fs.existsSync(envPath)) {
    const lines = fs.readFileSync(envPath, "utf-8").split("\n");
    for (const line of lines) {
      const trimmed = line.trim();
      if (!trimmed || trimmed.startsWith("#")) continue;
      const idx = trimmed.indexOf("=");
      if (idx > 0) {
        const k = trimmed.slice(0, idx).trim();
        const v = trimmed.slice(idx + 1).trim().replace(/^["']|["']$/g, "");
        if (!process.env[k]) process.env[k] = v;
      }
    }
  }
}

loadEnvFile(path.resolve("apps/site/.env.local"));
loadEnvFile(path.resolve("apps/site/.env"));
loadEnvFile(path.resolve(".env"));

const { Pool } = pg;

const args = process.argv.slice(2);
const eposta = args[0]?.trim().toLowerCase();
const planSlug = args[1]?.trim().toLowerCase();
let sureGun = 30;

let ozelAd = "";
let ozelSifre = "";

for (let i = 2; i < args.length; i++) {
  if (args[i] === "--ad" && args[i + 1]) {
    ozelAd = args[i + 1];
    i++;
  } else if (args[i] === "--sifre" && args[i + 1]) {
    ozelSifre = args[i + 1];
    i++;
  } else if (!isNaN(parseInt(args[i], 10))) {
    sureGun = parseInt(args[i], 10);
  }
}

if (!eposta || !planSlug) {
  console.log(`
❌ Kullanım:
  node scripts/abonelik-tanimla.mjs <eposta> <planSlug> [sureGun] [--ad "Adı"] [--sifre "Şifre"]

Planlar:
  gozlem     (499 TL/ay - Canlı telemetri, tek robot)
  operasyon  (1499 TL/ay - Kafa kontrolü, harita, çoklu robot)

Örnekler:
  node scripts/abonelik-tanimla.mjs ahmet@sirket.com operasyon 365
  node scripts/abonelik-tanimla.mjs mehmet@firma.com gozlem 30 --ad "Mehmet Bey" --sifre "Astro2026!"
`);
  process.exit(1);
}

const baglanti = process.env.DATABASE_URL;
if (!baglanti) {
  console.error("❌ DATABASE_URL çevre değişkeni tanımlı değil!");
  process.exit(1);
}

const pool = new Pool({ connectionString: baglanti });

function geciciSifreUret() {
  const chars = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789!@#$%";
  let sifre = "Astro-";
  const bytes = randomBytes(8);
  for (let i = 0; i < 8; i++) {
    sifre += chars[bytes[i] % chars.length];
  }
  return sifre + "!";
}

async function calistir() {
  const client = await pool.connect();
  try {
    let userRes = await client.query("SELECT id, name, email FROM users WHERE email = $1", [eposta]);
    let userId;
    let userName;
    let uretilenSifre = null;
    let yeniHesap = false;

    if (userRes.rows.length === 0) {
      // Kullanıcı yoksa otomatik oluştur
      yeniHesap = true;
      userId = randomUUID();
      userName = ozelAd || eposta.split("@")[0];
      uretilenSifre = ozelSifre || geciciSifreUret();

      // Better-Auth şifre hashleme
      let hash;
      try {
        const { createRequire } = await import("node:module");
        const require = createRequire(import.meta.url);
        const { hashPassword } = await import("better-auth/crypto");
        hash = await hashPassword(uretilenSifre);
      } catch {
        // Fallback salt:scrypt
        const { scryptSync } = await import("node:crypto");
        const salt = randomBytes(16).toString("hex");
        const derived = scryptSync(uretilenSifre, salt, 64).toString("hex");
        hash = `${salt}:${derived}`;
      }

      await client.query("BEGIN");

      // 1. users tablosuna ekle
      await client.query(
        `INSERT INTO users (id, name, email, email_verified, role, created_at, updated_at)
         VALUES ($1, $2, $3, true, 'customer', NOW(), NOW())`,
        [userId, userName, eposta]
      );

      // 2. accounts tablosuna parola kaydını ekle
      const accountId = randomUUID();
      await client.query(
        `INSERT INTO accounts (id, user_id, account_id, provider_id, password, created_at, updated_at)
         VALUES ($1, $2, $3, 'credential', $4, NOW(), NOW())`,
        [accountId, userId, userId, hash]
      );

      await client.query("COMMIT");
    } else {
      userId = userRes.rows[0].id;
      userName = userRes.rows[0].name;
    }

    const bitisTarihi = new Date(Date.now() + sureGun * 24 * 60 * 60 * 1000);
    const fiyatKurus = planSlug === "operasyon" ? 149900 : 49900;
    const planAd = planSlug === "operasyon" ? "Operasyon Planı" : "Gözlem Planı";

    // 3. Mevcut aboneliği kontrol et ve güncelle / ekle
    const subRes = await client.query(
      "SELECT id FROM subscriptions WHERE user_id = $1 AND status IN ('aktif', 'bekliyor', 'odenmedi') LIMIT 1",
      [userId]
    );

    let subId;
    if (subRes.rows.length > 0) {
      subId = subRes.rows[0].id;
      await client.query(
        `UPDATE subscriptions 
         SET product_slug = $1, status = 'aktif', provider = 'admin_tanimli', 
             price_minor = $2, current_period_end = $3, cancel_at = NULL 
         WHERE id = $4`,
        [planSlug, fiyatKurus, bitisTarihi, subId]
      );
    } else {
      subId = randomUUID();
      await client.query(
        `INSERT INTO subscriptions (id, user_id, product_slug, provider, provider_ref, status, price_minor, currency, current_period_end)
         VALUES ($1, $2, $3, 'admin_tanimli', $4, 'aktif', $5, 'TRY', $6)`,
        [subId, userId, planSlug, `manual_${Date.now()}`, fiyatKurus, bitisTarihi]
      );
    }

    // 4. Denetim günlüğüne ekle
    await client.query(
      `INSERT INTO audit_events (id, kind, payload, result, created_at)
       VALUES ($1, 'abonelik.admin_tanimlandi', $2, 'ok', NOW())`,
      [randomUUID(), JSON.stringify({ eposta, planSlug, sureGun, bitisTarihi: bitisTarihi.toISOString() })]
    );

    // Ekrana kurumsal bilgilendirme kartı bas
    console.log(`
╔════════════════════════════════════════════════════════════════════════╗
║             ASTRO V1 — YÖNETİCİ ABONELİK TANIMLAMA RAPORU              ║
╠════════════════════════════════════════════════════════════════════════╣
║  Durum           : ${yeniHesap ? "YENİ HESAP AÇILDI & ABONELİK AKTİF" : "MEVCUT HESAP ABONELİĞİ YENİLENDİ"}
║  Müşteri         : ${userName}
║  E-Posta Adresi  : ${eposta}
${yeniHesap ? `║  Geçici Parola   : ${uretilenSifre}
║  E-posta Onayı   : Doğrulandı (Aktif)
` : ""}║  Tanımlanan Plan : ${planAd} (${(fiyatKurus / 100).toFixed(2)} TL/ay)
║  Geçerlilik      : ${sureGun} Gün (${bitisTarihi.toLocaleDateString("tr-TR")} tarihine kadar)
║  Abonelik ID     : ${subId}
╚════════════════════════════════════════════════════════════════════════╝
`);

    if (yeniHesap) {
      console.log(`💡 MÜŞTERİYE VERİLECEK BİLGİLER:
--------------------------------------------------
Giriş Adresi : ${process.env.NEXT_PUBLIC_SITE_URL || "https://siteniz.com"}/giris
Kullanıcı Adı: ${eposta}
Parola       : ${uretilenSifre}
Planı        : ${planAd} (${sureGun} Gün)
--------------------------------------------------
(Müşteri giriş yaptıktan sonra Hesap sekmesinden şifresini değiştirebilir.)
`);
    } else {
      console.log(`✅ ${eposta} kullanıcısının aboneliği ${bitisTarihi.toLocaleDateString("tr-TR")} tarihine kadar uzatıldı.`);
    }
  } finally {
    client.release();
    await pool.end();
  }
}

calistir().catch((hata) => {
  console.error("❌ Hata oluştu:", hata.message);
  process.exit(1);
});
