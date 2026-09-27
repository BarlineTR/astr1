import pg from 'pg';

const pool = new pg.Pool({ connectionString: 'postgres://astro:astro@192.168.1.111:5432/astro' });

async function main() {
  const u = await pool.query("SELECT id FROM users WHERE email = 'admin@astro.com'");
  const userId = u.rows[0].id;

  await pool.query(`
    INSERT INTO subscriptions (id, user_id, product_slug, provider, provider_ref, status, price_minor, currency, current_period_end)
    VALUES ('sub_admin', $1, 'operasyon', 'admin_tanimli', 'manual_admin', 'aktif', 149900, 'TRY', NOW() + INTERVAL '365 days')
    ON CONFLICT (id) DO UPDATE SET user_id = $1, status = 'aktif'
  `, [userId]);

  await pool.query(`
    INSERT INTO device_grants (id, device_id, user_id, role, created_at)
    VALUES ('grant_admin', 'af2ffc9a-10c8-4ed2-875e-1ed10b0c1e99', $1, 'owner', NOW())
    ON CONFLICT (id) DO UPDATE SET user_id = $1
  `, [userId]);

  console.log("Admin user successfully granted Operasyon subscription and Jetson robot access!");
  await pool.end();
}

main().catch(console.error);
