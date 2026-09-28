import pg from 'pg';

const pool = new pg.Pool({ connectionString: 'postgres://astro:astro@192.168.1.111:5432/astro' });

async function main() {
  const adminId = 'jbyJfCjP95XEs009yt3fq12x5qoBXSjR'; // admin@astro.com
  const erenId = 'c67bec06-d1e7-412b-98b7-ea1d828b6ed4'; // eren@astro.com
  const deviceId = 'af2ffc9a-10c8-4ed2-875e-1ed10b0c1e99';

  // Set admin as owner
  await pool.query("UPDATE devices SET owner_user_id = $1 WHERE id = $2;", [adminId, deviceId]);

  // Give eren grant as operator/sahip as well
  await pool.query(`
    INSERT INTO device_grants (id, device_id, user_id, role, created_at)
    VALUES ('grant_eren', $1, $2, 'sahip', NOW())
    ON CONFLICT (id) DO UPDATE SET role = 'sahip';
  `, [deviceId, erenId]);

  // Make sure admin grant is also sahip
  await pool.query(`
    INSERT INTO device_grants (id, device_id, user_id, role, created_at)
    VALUES ('grant_admin', $1, $2, 'sahip', NOW())
    ON CONFLICT (id) DO UPDATE SET role = 'sahip';
  `, [deviceId, adminId]);

  console.log("✅ Device ownership and grants updated for both admin and eren!");
  await pool.end();
}

main().catch(console.error);
