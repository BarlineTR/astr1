import pg from 'pg';

const pool = new pg.Pool({ connectionString: 'postgres://astro:astro@192.168.1.111:5432/astro' });

async function main() {
  const tables = await pool.query("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public';");
  console.log("Tables:", tables.rows.map(r => r.table_name));

  for (const t of ['people', 'robot_settings']) {
    try {
      const cols = await pool.query(`SELECT column_name, data_type FROM information_schema.columns WHERE table_name = '${t}';`);
      console.log(`\nTable ${t} columns:`, cols.rows);
      const res = await pool.query(`SELECT id, device_id, name, role, notes, length(photo_base64) as photo_len, face_vector IS NOT NULL as has_vector FROM "people";`);
      console.log(`People in DB (${res.rows.length} rows):`);
      for (const r of res.rows) {
        console.log(`  - id: ${r.id}, name: ${r.name}, role: ${r.role}, notes: ${r.notes}, photo_len: ${r.photo_len}, has_vector: ${r.has_vector}`);
      }
    } catch (e) {
      console.log(`Table ${t} error:`, e.message);
    }
  }

  await pool.end();
}

main().catch(console.error);
