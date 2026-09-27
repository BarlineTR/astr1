import fs from "node:fs";
import path from "node:path";
import pg from "pg";
import { createHash, randomBytes, randomUUID } from "node:crypto";
import paramiko from "child_process";

const { Pool } = pg;
const dbUrl = "postgres://astro:astro@192.168.1.111:5432/astro";
const pool = new Pool({ connectionString: dbUrl });

const ALFABE = "ABCDEFGHJKMNPQRSTUVWXYZ23456789";
function eslestirmeKoduUret() {
  const bayt = randomBytes(16);
  const harfler = Array.from(bayt, (b) => ALFABE[b % ALFABE.length]).join("");
  const gruplar = [];
  for (let i = 0; i < 4; i++) {
    gruplar.push(harfler.slice(i * 4, (i + 1) * 4));
  }
  return gruplar.join("-");
}

function koduOzetle(kod) {
  return createHash("sha256").update(kod.trim().toUpperCase()).digest("hex");
}

async function eslestir() {
  const client = await pool.connect();
  try {
    // 1. eren@astro.com kullanıcısını bul
    const userRes = await client.query("SELECT id FROM users WHERE email = $1", ["eren@astro.com"]);
    if (userRes.rows.length === 0) {
      console.error("Kullanıcı bulunamadı");
      return;
    }
    const userId = userRes.rows[0].id;
    const serial = "ASTRO-V1-000123";
    const name = "ASTRO Jetson Robot";

    const kod = eslestirmeKoduUret();
    const kodOzet = koduOzetle(kod);
    const expiresAt = new Date(Date.now() + 24 * 60 * 60 * 1000);

    const devRes = await client.query("SELECT id FROM devices WHERE serial = $1", [serial]);
    let deviceId;

    if (devRes.rows.length > 0) {
      deviceId = devRes.rows[0].id;
      await client.query(
        `UPDATE devices 
         SET pairing_code_hash = $1, pairing_expires_at = $2, owner_user_id = $3, status = 'eslestirme-bekliyor', revoked_at = NULL 
         WHERE id = $4`,
        [kodOzet, expiresAt, userId, deviceId]
      );
      console.log(`Cihaz güncellendi. ID: ${deviceId}`);
    } else {
      deviceId = randomUUID();
      await client.query(
        `INSERT INTO devices (id, serial, name, owner_user_id, pairing_code_hash, pairing_expires_at, status)
         VALUES ($1, $2, $3, $4, $5, $6, 'eslestirme-bekliyor')`,
        [deviceId, serial, name, userId, kodOzet, expiresAt]
      );
      console.log(`Yeni cihaz oluşturuldu. ID: ${deviceId}`);
    }

    console.log(`🔑 Üretilen Eşleştirme Kodu: ${kod}`);

    // 2. Site üzerinden eşleştirme çağrısı yap (POST /api/cihaz/eslestir)
    const resp = await fetch("http://localhost:3000/api/cihaz/eslestir", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ kod, serial, firmware: "astro-v1.0" }),
    });

    if (!resp.ok) {
      console.error("Eşleştirme API hatası:", resp.status, await resp.text());
      return;
    }

    const data = await resp.json();
    console.log("🎉 EŞLEŞTİRME BAŞARILI!");
    console.log("Cihaz ID  :", data.cihazId);
    console.log("Jeton     :", data.token);

    // 3. Jeton dosyasını yerel ve Jetson için hazırla
    const tokenPayload = {
      token: data.token,
      gecitUrl: "ws://192.168.1.102:8420",
      serial: serial,
    };

    fs.writeFileSync("scratch_token.json", JSON.stringify(tokenPayload, null, 2));
    console.log("Jeton 'scratch_token.json' dosyasına kaydedildi.");
  } finally {
    client.release();
    await pool.end();
  }
}

eslestir().catch(console.error);
