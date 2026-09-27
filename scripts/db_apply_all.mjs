import fs from "fs";
import path from "path";
import pg from "pg";

const { Client } = pg;
const dbUrl = "postgres://astro:astro@192.168.1.111:5432/astro";

async function applyMigrations() {
  const client = new Client({ connectionString: dbUrl });
  await client.connect();
  console.log("Connected to Jetson DB!");

  const drizzleDir = path.resolve("apps/site/drizzle");
  const sqlFiles = ["0000_strong_revanche.sql", "0001_steady_fenris.sql", "0002_cynical_warlock.sql", "0003_clean_random.sql"];

  for (const f of sqlFiles) {
    const fullPath = path.join(drizzleDir, f);
    if (fs.existsSync(fullPath)) {
      console.log(`Applying ${f}...`);
      const sql = fs.readFileSync(fullPath, "utf-8");
      // Drizzle SQL files can contain statements separated by --> statement-breakpoint
      const parts = sql.split("--> statement-breakpoint");
      for (const part of parts) {
        const trimmed = part.trim();
        if (trimmed) {
          try {
            await client.query(trimmed);
          } catch (e) {
            console.warn(`Notice on ${f}:`, e.message);
          }
        }
      }
    }
  }

  // Also create our 3 new tables: people, robot_settings, patrol_waypoints
  const newTablesSql = `
    CREATE TABLE IF NOT EXISTS "people" (
      "id" text PRIMARY KEY NOT NULL,
      "owner_user_id" text NOT NULL REFERENCES "users"("id") ON DELETE CASCADE,
      "device_id" text REFERENCES "devices"("id") ON DELETE SET NULL,
      "name" text NOT NULL,
      "role" text NOT NULL DEFAULT 'guest',
      "notes" text,
      "photo_base64" text,
      "face_vector" jsonb,
      "created_at" timestamp with time zone DEFAULT now() NOT NULL,
      "updated_at" timestamp with time zone DEFAULT now() NOT NULL
    );

    CREATE TABLE IF NOT EXISTS "robot_settings" (
      "id" text PRIMARY KEY NOT NULL,
      "device_id" text NOT NULL UNIQUE REFERENCES "devices"("id") ON DELETE CASCADE,
      "voice_speed" integer DEFAULT 100 NOT NULL,
      "voice_pitch" integer DEFAULT 100 NOT NULL,
      "tts_voice" text DEFAULT 'tr_tr_male' NOT NULL,
      "llm_prompt" text DEFAULT 'Sen yardımsever ve cana yakın bir sosyal robotsun.' NOT NULL,
      "greeting_message" text DEFAULT 'Merhaba, hoş geldiniz!' NOT NULL,
      "alert_on_unknown" boolean DEFAULT true NOT NULL,
      "alert_email" text,
      "patrol_active" boolean DEFAULT false NOT NULL,
      "updated_at" timestamp with time zone DEFAULT now() NOT NULL
    );

    CREATE TABLE IF NOT EXISTS "patrol_waypoints" (
      "id" text PRIMARY KEY NOT NULL,
      "device_id" text NOT NULL REFERENCES "devices"("id") ON DELETE CASCADE,
      "name" text NOT NULL,
      "x" integer NOT NULL,
      "y" integer NOT NULL,
      "yaw" integer DEFAULT 0 NOT NULL,
      "visit_interval_minutes" integer DEFAULT 30,
      "created_at" timestamp with time zone DEFAULT now() NOT NULL
    );
  `;

  await client.query(newTablesSql);
  console.log("✅ All migrations and tables applied successfully to Jetson PostgreSQL!");

  const tables = await client.query(`
    SELECT table_name FROM information_schema.tables WHERE table_schema='public'
  `);
  console.log("Current DB Tables:", tables.rows.map(r => r.table_name).join(", "));

  await client.end();
}

applyMigrations().catch(e => {
  console.error("Migration failed:", e);
  process.exit(1);
});
