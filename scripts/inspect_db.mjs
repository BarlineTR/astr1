import pg from 'pg';

const pool = new pg.Pool({ connectionString: 'postgres://astro:astro@192.168.1.111:5432/astro' });

async function main() {
  const tables = await pool.query("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public';");
  console.log("Tables:", tables.rows.map(r => r.table_name));

  for (const t of ['user', 'users', 'account', 'devices', 'device_grants']) {
    try {
      const res = await pool.query(`SELECT * FROM "${t}" LIMIT 3;`);
      console.log(`\nTable ${t}:`, res.rows);
    } catch (e) {
      console.log(`Table ${t} error:`, e.message);
    }
  }

  await pool.end();
}

main().catch(console.error);
