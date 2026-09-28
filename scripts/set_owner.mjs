import pg from 'pg';

const pool = new pg.Pool({ connectionString: 'postgres://astro:astro@192.168.1.111:5432/astro' });

async function main() {
  const u = await pool.query('SELECT id FROM "user" WHERE email = \'admin@astro.com\'');
  const adminId = u.rows[0].id;

  await pool.query("UPDATE devices SET owner_user_id = $1 WHERE serial = 'ASTRO-V1-000123'", [adminId]);
  await pool.query("UPDATE device_grants SET role = 'sahip', user_id = $1 WHERE device_id = 'af2ffc9a-10c8-4ed2-875e-1ed10b0c1e99'", [adminId]);

  console.log("Device owner updated successfully to admin:", adminId);
  await pool.end();
}

main().catch(console.error);
