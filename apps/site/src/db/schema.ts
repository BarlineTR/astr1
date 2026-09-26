import {
  boolean,
  index,
  integer,
  jsonb,
  pgTable,
  text,
  timestamp,
  uniqueIndex,
} from "drizzle-orm/pg-core";

/**
 * Veritabanı şeması.
 *
 * Faz 2'de yalnızca kimlik, onay, iletişim ve cihaz iskeleti dolu. Ödeme
 * tabloları (products, orders, payments, subscriptions, webhook_events) tasarım
 * belgesi §7'de duruyor ve ödeme fazında eklenecek — şema baştan bunu taşıyacak
 * şekilde düşünüldüğü için eklemek göç yazmak olacak, yeniden yazmak değil.
 */

/** Kullanıcı rolleri. Cihaz yetkisi bundan ayrıdır (bkz. deviceGrants). */
export const ROLLER = ["customer", "operator", "admin"] as const;
export type Rol = (typeof ROLLER)[number];

/* ─────────────────────────────  Kimlik  ───────────────────────────── */

/*
 * users / sessions / accounts / verifications tabloları better-auth'un
 * beklediği adlara sahip. Kendi alanlarımız (role, company, phone) eklendi;
 * better-auth bunları additionalFields ile tanır.
 */

export const users = pgTable("users", {
  id: text("id").primaryKey(),
  name: text("name").notNull(),
  email: text("email").notNull().unique(),
  emailVerified: boolean("email_verified").notNull().default(false),
  image: text("image"),

  /** Yetki seviyesi. Cihaz erişimi ayrıca deviceGrants'tan gelir. */
  role: text("role").$type<Rol>().notNull().default("customer"),
  company: text("company"),
  phone: text("phone"),

  createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
  updatedAt: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
  /**
   * Hesabı devre dışı bırakır — KVKK silme talebi bu değildir.
   * Silme talebinde kayıt gerçekten silinir ve denetim kaydında yalnızca
   * kimliksizleştirilmiş iz kalır.
   */
  deletedAt: timestamp("deleted_at", { withTimezone: true }),
});

export const sessions = pgTable(
  "sessions",
  {
    id: text("id").primaryKey(),
    userId: text("user_id")
      .notNull()
      .references(() => users.id, { onDelete: "cascade" }),
    token: text("token").notNull().unique(),
    expiresAt: timestamp("expires_at", { withTimezone: true }).notNull(),
    ipAddress: text("ip_address"),
    userAgent: text("user_agent"),
    createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
    updatedAt: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
  },
  (t) => [index("sessions_user_idx").on(t.userId)],
);

export const accounts = pgTable(
  "accounts",
  {
    id: text("id").primaryKey(),
    userId: text("user_id")
      .notNull()
      .references(() => users.id, { onDelete: "cascade" }),
    accountId: text("account_id").notNull(),
    providerId: text("provider_id").notNull(),
    /** Parola özeti; parolanın kendisi hiçbir yerde tutulmaz. */
    password: text("password"),
    accessToken: text("access_token"),
    refreshToken: text("refresh_token"),
    idToken: text("id_token"),
    accessTokenExpiresAt: timestamp("access_token_expires_at", { withTimezone: true }),
    refreshTokenExpiresAt: timestamp("refresh_token_expires_at", { withTimezone: true }),
    scope: text("scope"),
    createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
    updatedAt: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
  },
  (t) => [index("accounts_user_idx").on(t.userId)],
);

export const verifications = pgTable(
  "verifications",
  {
    id: text("id").primaryKey(),
    identifier: text("identifier").notNull(),
    value: text("value").notNull(),
    expiresAt: timestamp("expires_at", { withTimezone: true }).notNull(),
    createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
    updatedAt: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
  },
  (t) => [index("verifications_identifier_idx").on(t.identifier)],
);

/* ──────────────────────────  KVKK onayları  ────────────────────────── */

/**
 * Verilen onaylar.
 *
 * `textVersion` zorunlu: onayın hangi metne verildiği bilinmeden onay
 * ispatlanamaz. Metin değiştiğinde sürüm artar ve eski onaylar eski sürüme
 * bağlı kalır.
 *
 * `userId` boş olabilir — iletişim formu girişsiz de doldurulabiliyor ve o
 * onayın da kaydı tutulmalı.
 */
export const consents = pgTable(
  "consents",
  {
    id: text("id").primaryKey(),
    userId: text("user_id").references(() => users.id, { onDelete: "set null" }),
    /** "kvkk", "cerez", "ticari-ileti" gibi. */
    kind: text("kind").notNull(),
    textVersion: text("text_version").notNull(),
    ipAddress: text("ip_address"),
    userAgent: text("user_agent"),
    createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
  },
  (t) => [index("consents_user_idx").on(t.userId), index("consents_kind_idx").on(t.kind)],
);

/* ──────────────────────────  İletişim / teklif  ────────────────────── */

export const contactRequests = pgTable(
  "contact_requests",
  {
    id: text("id").primaryKey(),
    /** "iletisim" veya "teklif". */
    kind: text("kind").notNull(),
    name: text("name").notNull(),
    email: text("email").notNull(),
    company: text("company"),
    phone: text("phone"),
    message: text("message").notNull(),
    sourcePage: text("source_page"),
    status: text("status").notNull().default("yeni"),
    createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
  },
  (t) => [index("contact_kind_idx").on(t.kind), index("contact_status_idx").on(t.status)],
);

/* ────────────────────────────────  Cihazlar  ──────────────────────────── */

/**
 * Robotlar.
 *
 * Jetonun kendisi saklanmaz, yalnızca özeti: veritabanı sızsa bile jetonlar
 * doğrudan kullanılamaz. İptal `revokedAt` ile yapılır, satır silinmez —
 * denetim kayıtları cihaza referans veriyor.
 */
export const devices = pgTable(
  "devices",
  {
    id: text("id").primaryKey(),
    serial: text("serial").notNull().unique(),
    name: text("name").notNull(),
    ownerUserId: text("owner_user_id").references(() => users.id, { onDelete: "set null" }),
    tokenHash: text("token_hash"),
    firmwareVersion: text("firmware_version"),
    status: text("status").notNull().default("kayitli"),
    lastSeenAt: timestamp("last_seen_at", { withTimezone: true }),
    createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
    revokedAt: timestamp("revoked_at", { withTimezone: true }),
  },
  (t) => [index("devices_owner_idx").on(t.ownerUserId)],
);

/**
 * Cihaz yetkileri.
 *
 * Kullanıcı rolünden ayrı: bir operatör yalnızca kendisine verilmiş cihazı
 * görür. Rol "kullanıcı ne yapabilir"i, bu tablo "hangi cihazda"yı söyler.
 */
export const deviceGrants = pgTable(
  "device_grants",
  {
    id: text("id").primaryKey(),
    deviceId: text("device_id")
      .notNull()
      .references(() => devices.id, { onDelete: "cascade" }),
    userId: text("user_id")
      .notNull()
      .references(() => users.id, { onDelete: "cascade" }),
    /** "operator" komut gönderebilir, "viewer" yalnızca izler. */
    role: text("role").$type<"operator" | "viewer">().notNull(),
    grantedBy: text("granted_by").references(() => users.id, { onDelete: "set null" }),
    expiresAt: timestamp("expires_at", { withTimezone: true }),
    createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
  },
  (t) => [uniqueIndex("device_grants_uniq").on(t.deviceId, t.userId)],
);

/* ──────────────────────────  Denetim kaydı  ────────────────────────── */

/**
 * Yalnızca ekleme.
 *
 * Güncelleme ve silme yolu kodda hiç yazılmaz; `updatedAt` kolonu bilerek yok,
 * çünkü olması güncellenmesini davet eder ve kaydın değeri tam olarak
 * değiştirilememesinden gelir.
 */
export const auditEvents = pgTable(
  "audit_events",
  {
    id: text("id").primaryKey(),
    actorUserId: text("actor_user_id").references(() => users.id, { onDelete: "set null" }),
    deviceId: text("device_id").references(() => devices.id, { onDelete: "set null" }),
    /** "giris", "cikis", "yetki.red", "cihaz.komut" gibi. */
    kind: text("kind").notNull(),
    payload: jsonb("payload"),
    /** "ok" ya da hata kısa adı. */
    result: text("result").notNull(),
    ipAddress: text("ip_address"),
    createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
  },
  (t) => [
    index("audit_actor_idx").on(t.actorUserId),
    index("audit_device_idx").on(t.deviceId),
    index("audit_kind_idx").on(t.kind),
    index("audit_created_idx").on(t.createdAt),
  ],
);
