# Faz 0+1+2 — Kurumsal site, SEO ve giriş/çıkış sistemi: uygulama planı

> **Ajan işçiler için:** GEREKLİ ALT BECERİ: bu planı görev görev uygulamak için
> `superpowers:subagent-driven-development` (önerilen) ya da
> `superpowers:executing-plans` kullanın. Adımlar takip için onay kutusu
> (`- [ ]`) sözdizimindedir.

**Hedef:** ASTRO tanıtım sitesini, içeriği sunucuda üretilen kurumsal bir siteye
dönüştürmek ve arkasına çalışan bir kimlik/oturum sistemi kurmak; kontrol konsolu
yalnızca girişten sonra erişilebilir olsun.

**Mimari:** npm workspaces monorepo. `packages/protocol` telemetri sözleşmesini zod
şemaları olarak tutar ve JSON Schema üretir. `apps/site` Next.js 16 App Router ile
bütün HTTP yüzeyini taşır (pazarlama, SEO, oturum, panel). `apps/gateway` mevcut
Fastify sunucusudur ve Faz 4'te robot köprüsü olacak. Çerçeveden bağımsız olan üç
parça — three.js sahnesi, kaydırma anlatısı, telemetri istemcisi — **hiç
değiştirilmeden** taşınır ve React istemci bileşenleri onları `useEffect` içinde
sürer. CSS tek satır değişmez; bu yüzden sınıf adları birebir korunmalıdır.

**Teknoloji yığını:** Next.js 16.3.6 (App Router) · React 19.3.0 · TypeScript 5.6 ·
zod 4.6.5 · Drizzle ORM 0.45.3 + drizzle-kit 0.31.11 · PostgreSQL 16 (Docker) ·
better-auth 1.7.6 · Fastify 5 · three.js 0.170 · vitest 2.1 · Playwright 1.63 ·
Resend 6.30

**Spec:** `docs/superpowers/specs/2026-09-26-kurumsal-web-sitesi-design.md`

## Global kısıtlar

Her görevin gereksinimleri örtük olarak bu bölümü içerir.

- **Node >= 20.9.0** (Next 16'nın şartı). Ortamdaki sürüm 20.20.2 — yeterli.
- **Tailwind kullanılmaz** (D3). Bütün stil `packages/ui/styles/*.css` içindeki
  mevcut dosyalardan gelir. Yeni renk, yeni yazı tipi, yeni gölge eklenmez; her
  değer `tokens.css` içindeki bir belirteçten okunur.
- **CSS sınıf adları değişmez.** `layout.css` 643 satırdır ve `showcase.ts` sınıf
  adlarıyla çalışır. React bileşenleri aynı sınıf adlarını aynı hiyerarşide
  üretmek zorundadır.
- **Vurgu rengi üç işte kullanılır:** bölüm numarası, etkin durum, ölçülmüş değer.
  Başka yerde `--accent` kullanılmaz.
- **Bütün kopya içerik modüllerinde durur** (`apps/site/src/data/*.ts`). Bileşenin
  içine düz metin yazılmaz — İngilizce sürümün yolu bu şekilde açık kalır (D11).
- **Kurum bilgileri yer tutucudur** ve `apps/site/src/data/kurum.ts` içinde
  `YER_TUTUCU` sabitiyle işaretlenir (R3).
- **Fiyatlar uydurmadır** ve `GELISTIRME_FIYATI` ile işaretlenir (R4).
- **`astro-hero.glb` yerinde kalır** (D12, R1). Yol tek bir modülde tutulur.
- **Tutarlar her zaman tam sayı kuruştur.** Kayan noktalı para yok.
- **Ölçülmüş değerler metinde geçer:** ±85°, 72°, 121°, 0,4–2,5 m. Bunlar
  `packages/protocol/src/limits.ts` içindeki sabitlerden okunur, elle yazılmaz.
- **Testler `npm test` ile koşar** (vitest). Mevcut 16 test her görevin sonunda
  geçmeye devam eder; bir görev onları kırıyorsa görev bitmemiştir.
- **Yorumlar Türkçe**, mevcut kod tabanının üslubuyla: ne yaptığını değil neden
  öyle olduğunu anlatır.
- **Her görev commit ile biter.** Commit mesajı Türkçe, `tür(kapsam): özet` biçiminde.

---

# Faz 0 — İskelet

## Görev 1: `packages/protocol` ve kırık typecheck'in onarımı

Bugün `npm run typecheck` `error TS5083` ile ölüyor çünkü kökte `tsconfig.json` yok.
Bu görev monorepo iskeletini kurar, `shared/` klasörünü sözleşme paketine çevirir ve
sözleşmeyi zod şemalarına taşır — ağ geçidi istemciden geleni doğrulamak zorunda
olduğu için tipler tek başına yetmez.

**Dosyalar:**
- Oluştur: `tsconfig.json` (kök, proje referanslı)
- Oluştur: `packages/protocol/package.json`
- Oluştur: `packages/protocol/tsconfig.json`
- Oluştur: `packages/protocol/src/index.ts`
- Oluştur: `packages/protocol/src/schema.ts`
- Oluştur: `packages/protocol/src/json-schema.ts`
- Oluştur: `packages/protocol/test/schema.test.ts`
- Taşı: `shared/protocol.ts` → `packages/protocol/src/protocol.ts`
- Taşı: `shared/limits.ts` → `packages/protocol/src/limits.ts`
- Taşı: `shared/scene-state.ts` → `packages/protocol/src/scene-state.ts`
- Taşı: `shared/demo-driver.ts` → `packages/protocol/src/demo-driver.ts`
- Taşı: `shared/demo-driver.test.ts` → `packages/protocol/test/demo-driver.test.ts`
- Değiştir: `package.json` (workspaces: `apps/*`, `packages/*`)
- Değiştir: `client/src/pages/console.ts` (import yolu)
- Değiştir: `client/src/entries/console.ts`, `client/src/entries/home.ts` (import yolu)
- Değiştir: `server/src/index.ts`, `server/tsconfig.json` (import yolu)

**Arayüzler:**
- Üretir: `@astro/protocol` paketi şunları dışa verir — `HEAD_YAW_LIMIT_DEG`,
  `ENCODER_TICKS_PER_DEG`, `HEAD_DEADBAND_DEG`, `CAMERA_HFOV_DEG`,
  `CAMERA_VFOV_DEG`, `AUDIO_CHAT_CONE_DEG`, `AUDIO_REACHABLE_DEG`,
  `IDLE_STATE`, `DemoDriver`, tip olarak `Telemetry`, `Command`, `ServerMessage`,
  `SceneState`, `SceneDriver`, `AttentionOwner`, `TelemetrySource`,
  ve zod şemaları `telemetrySchema`, `commandSchema`, `serverMessageSchema`,
  `PROTOCOL_VERSION`, `protocolJsonSchema()`.

- [ ] **Adım 1: Paket iskeletini kur**

```bash
mkdir -p packages/protocol/src packages/protocol/test
git mv shared/protocol.ts packages/protocol/src/protocol.ts
git mv shared/limits.ts packages/protocol/src/limits.ts
git mv shared/scene-state.ts packages/protocol/src/scene-state.ts
git mv shared/demo-driver.ts packages/protocol/src/demo-driver.ts
git mv shared/demo-driver.test.ts packages/protocol/test/demo-driver.test.ts
rmdir shared
```

`packages/protocol/test/demo-driver.test.ts` içindeki `from "./demo-driver"`
importları `from "../src/demo-driver"` olur.

- [ ] **Adım 2: Paket bildirimi**

`packages/protocol/package.json`:

```json
{
  "name": "@astro/protocol",
  "private": true,
  "version": "0.1.0",
  "type": "module",
  "exports": { ".": "./src/index.ts" },
  "types": "./src/index.ts",
  "dependencies": { "zod": "^4.6.5" }
}
```

Kaynak TypeScript olarak dışa verilir; derlenmiş çıktı tutulmaz. Tüketiciler
(Next, Vite, tsx) TS'i kendileri işler — ara bir derleme adımı hem yavaş hem de
bir daha senkronize tutulması gereken bir kopya demek.

`packages/protocol/tsconfig.json`:

```json
{
  "extends": "../../tsconfig.base.json",
  "compilerOptions": { "lib": ["ES2022"], "noEmit": true },
  "include": ["src", "test"]
}
```

- [ ] **Adım 3: Başarısız testi yaz**

`packages/protocol/test/schema.test.ts`:

```ts
import { describe, expect, it } from "vitest";

import {
  PROTOCOL_VERSION,
  commandSchema,
  protocolJsonSchema,
  telemetrySchema,
} from "../src/index";
import { HEAD_YAW_LIMIT_DEG } from "../src/limits";

/** Ağ geçidinin robota yollayacağı örnek: alanların hepsi dolu. */
const gecerliTelemetri = {
  t: 1_759_000_000_000,
  source: "mock",
  connected: true,
  head: { desiredYawDeg: 12.5, actualYawDeg: 11.8, encoderOk: true },
  gaze: { attentionOwner: "visual", visualValid: true, state: "TRACKING" },
  audio: { doaDeg: -30, confidence: 0.8, vad: true },
  faces: [{ name: "Ada", confidence: 0.91, box: [0.1, 0.2, 0.3, 0.4], distanceM: 1.2 }],
  safety: { eStop: false, watchdogOk: true },
};

describe("telemetrySchema", () => {
  it("geçerli telemetriyi kabul eder", () => {
    expect(telemetrySchema.parse(gecerliTelemetri)).toMatchObject({ source: "mock" });
  });

  it("tanınmayan dikkat sahibini reddeder", () => {
    const bozuk = { ...gecerliTelemetri, gaze: { ...gecerliTelemetri.gaze, attentionOwner: "kulak" } };
    expect(() => telemetrySchema.parse(bozuk)).toThrow();
  });

  it("kutu dört elemandan kısa olamaz", () => {
    const bozuk = { ...gecerliTelemetri, faces: [{ ...gecerliTelemetri.faces[0], box: [0.1, 0.2] }] };
    expect(() => telemetrySchema.parse(bozuk)).toThrow();
  });
});

describe("commandSchema", () => {
  it("sınır içindeki hedefi kabul eder", () => {
    expect(commandSchema.parse({ kind: "head.target", yawDeg: 40 })).toEqual({
      kind: "head.target",
      yawDeg: 40,
    });
  });

  /*
   * Kırpma köprüde yapılır ama şema yine de sınırı zorlar: istemciye
   * güvenilmediği için iki katman da gerekli.
   */
  it("sınırın ötesindeki hedefi reddeder", () => {
    expect(() => commandSchema.parse({ kind: "head.target", yawDeg: HEAD_YAW_LIMIT_DEG + 1 })).toThrow();
  });

  it("tanınmayan komut türünü reddeder", () => {
    expect(() => commandSchema.parse({ kind: "kafa.patlat" })).toThrow();
  });
});

describe("protocolJsonSchema", () => {
  /*
   * ROS tarafındaki Python ajanı bu şemaya karşı kendi testini koşar. Üretimin
   * çalıştığını burada doğrulamak, iki depo arasındaki tek bağın kopmadığını
   * garanti eder.
   */
  it("sürüm taşıyan bir JSON Schema üretir", () => {
    const schema = protocolJsonSchema();
    expect(schema.$id).toContain(PROTOCOL_VERSION);
    expect(schema.$defs).toHaveProperty("Telemetry");
    expect(schema.$defs).toHaveProperty("Command");
  });
});
```

- [ ] **Adım 4: Testi koş, başarısız olduğunu gör**

Çalıştır: `npm test -- packages/protocol`
Beklenen: FAIL — `Cannot find module '../src/index'`

- [ ] **Adım 5: Şemaları yaz**

`packages/protocol/src/schema.ts`. Mevcut `protocol.ts` içindeki yorumlar buraya
taşınır; alanların **neden** öyle olduğu bilgisinin kaybolmaması önemli.

```ts
import { z } from "zod";

import { HEAD_YAW_LIMIT_DEG } from "./limits";

/**
 * Sözleşmenin ana sürümü.
 *
 * Ajan ile ağ geçidi farklı ana sürümdeyse bağlantı reddedilir. Sessizce yanlış
 * alan okumak, anlaşılır bir hatadan çok daha pahalıdır.
 */
export const PROTOCOL_VERSION = "1";

/** Dikkatin sahibi — /gaze/debug içindeki `attention_owner` alanının karşılığı. */
export const attentionOwnerSchema = z.enum(["visual", "audio", "none"]);

/** Telemetrinin nereden geldiği. Arayüzde her zaman görünür olmalıdır. */
export const telemetrySourceSchema = z.enum(["mock", "robot"]);

export const headTelemetrySchema = z.object({
  /** Gaze döngüsünün istediği açı (derece, +sol / −sağ, base_link çerçevesi). */
  desiredYawDeg: z.number(),
  /** Encoder'ın ölçtüğü gerçek açı. Geri besleme yoksa `encoderOk=false`. */
  actualYawDeg: z.number(),
  /** Akmıyorsa bütün kerterizler çöker — bu bayrak arayüzde yutulmamalıdır. */
  encoderOk: z.boolean(),
});

export const gazeTelemetrySchema = z.object({
  attentionOwner: attentionOwnerSchema,
  visualValid: z.boolean(),
  /** SocialGazeFSM durum adı (ör. "TRACKING", "SEARCHING"). */
  state: z.string(),
});

export const audioTelemetrySchema = z.object({
  /** Kafaya göre değil, gövdeye göre ses azimutu. Yön yoksa null. */
  doaDeg: z.number().nullable(),
  confidence: z.number().min(0).max(1),
  vad: z.boolean(),
});

export const faceObservationSchema = z.object({
  name: z.string().nullable(),
  /** Eşiğin altındaki gözlem hiç geçerli sayılmaz. */
  confidence: z.number().min(0).max(1),
  /** Normalize edilmiş kare içi kutu: [x, y, w, h]. */
  box: z.tuple([z.number(), z.number(), z.number(), z.number()]),
  /** Metre cinsinden derinlik; stereo yoksa null. */
  distanceM: z.number().nullable(),
});

export const safetyTelemetrySchema = z.object({
  eStop: z.boolean(),
  /** Firmware heartbeat'i 500 ms içinde yenilendi mi. */
  watchdogOk: z.boolean(),
});

export const telemetrySchema = z.object({
  /** Köprünün damgaladığı zaman (ms, epoch). Gecikme ölçümü buna dayanır. */
  t: z.number(),
  source: telemetrySourceSchema,
  /** `false` iken alanlar son bilinen değerdir. */
  connected: z.boolean(),
  head: headTelemetrySchema,
  gaze: gazeTelemetrySchema,
  audio: audioTelemetrySchema,
  faces: z.array(faceObservationSchema),
  safety: safetyTelemetrySchema,
});

/**
 * İstemciden gelen komutlar.
 *
 * Kırpma köprüde yapılır; buradaki sınır ikinci katmandır. İstemciye güvenilmez
 * ve iki katmanın ikisi de ucuz.
 */
export const commandSchema = z.discriminatedUnion("kind", [
  z.object({
    kind: z.literal("head.target"),
    yawDeg: z.number().min(-HEAD_YAW_LIMIT_DEG).max(HEAD_YAW_LIMIT_DEG),
  }),
  z.object({ kind: z.literal("head.center") }),
  z.object({ kind: z.literal("estop"), engaged: z.boolean() }),
]);

export const serverMessageSchema = z.discriminatedUnion("kind", [
  z.object({ kind: z.literal("telemetry"), payload: telemetrySchema }),
  z.object({
    kind: z.literal("hello"),
    v: z.string(),
    source: telemetrySourceSchema,
    limits: z.object({ headYawDeg: z.number() }),
  }),
  z.object({ kind: z.literal("error"), message: z.string() }),
]);

export type Telemetry = z.infer<typeof telemetrySchema>;
export type Command = z.infer<typeof commandSchema>;
export type ServerMessage = z.infer<typeof serverMessageSchema>;
export type AttentionOwner = z.infer<typeof attentionOwnerSchema>;
export type TelemetrySource = z.infer<typeof telemetrySourceSchema>;
export type FaceObservation = z.infer<typeof faceObservationSchema>;
```

`packages/protocol/src/json-schema.ts`:

```ts
import { z } from "zod";

import { PROTOCOL_VERSION, commandSchema, telemetrySchema } from "./schema";

/**
 * ROS tarafındaki Python ajanı için makine okunur sözleşme.
 *
 * zod 4 JSON Schema üretimini kendi içinde taşıyor; ayrı bir dönüştürücü paket
 * bir bağımlılık ve bir daha güncel tutulması gereken kopya demekti.
 */
export function protocolJsonSchema(): Record<string, unknown> {
  return {
    $id: `https://astro.example/schema/protocol-${PROTOCOL_VERSION}.json`,
    $defs: {
      Telemetry: z.toJSONSchema(telemetrySchema),
      Command: z.toJSONSchema(commandSchema),
    },
  };
}
```

`packages/protocol/src/index.ts`:

```ts
export * from "./limits";
export * from "./scene-state";
export * from "./schema";
export * from "./json-schema";
export { DemoDriver } from "./demo-driver";
```

`packages/protocol/src/protocol.ts` silinir: içeriği `schema.ts`e taşındı ve iki
kopya tutmak sözleşmenin tek olma iddiasını bozar.

```bash
git rm packages/protocol/src/protocol.ts
```

- [ ] **Adım 6: Testi koş, geçtiğini gör**

Çalıştır: `npm test -- packages/protocol`
Beklenen: PASS — şema testleri + taşınan 6 `demo-driver` testi

- [ ] **Adım 7: Kök tsconfig'i kur, typecheck'i onar**

`tsconfig.json` (kök):

```json
{
  "files": [],
  "references": [
    { "path": "./packages/protocol" },
    { "path": "./client" },
    { "path": "./server" }
  ]
}
```

`tsconfig.base.json`e yol eşlemesi eklenir — böylece her tüketici aynı adı kullanır:

```json
{
  "compilerOptions": {
    "baseUrl": ".",
    "paths": { "@astro/protocol": ["./packages/protocol/src/index.ts"] }
  }
}
```

Proje referansları `composite` ister; `packages/protocol/tsconfig.json`,
`client/tsconfig.json` ve `server/tsconfig.json`e
`"composite": true, "declaration": true, "declarationDir": ".tsbuild"` eklenir ve
`.tsbuild` `.gitignore`a yazılır.

Kök `package.json`:

```json
{
  "workspaces": ["apps/*", "packages/*", "client", "server"],
  "scripts": {
    "typecheck": "tsc -b --pretty false",
    "test": "vitest run"
  }
}
```

`client` ve `server` geçici olarak listede kalır; Görev 2 ve 8'de düşecekler.

- [ ] **Adım 8: Import yollarını güncelle**

`client/src/pages/console.ts`, `client/src/entries/console.ts`,
`client/src/entries/home.ts`, `client/src/site/showcase.ts` ve `server/src/index.ts`
içindeki `../../shared/...` ve `../../../shared/...` yolları `@astro/protocol`
olur. `client/vite.config.ts`e takma ad eklenir:

```ts
resolve: {
  alias: { "@astro/protocol": resolve(import.meta.dirname, "../packages/protocol/src/index.ts") },
},
```

`server/tsconfig.json` içindeki `"include": ["src", "../shared"]` →
`["src", "../packages/protocol/src"]`.

`shared/` altındaki `demo-driver` importu `client/src/entries/home.ts` içinde
`import("../../../shared/demo-driver")` olarak dinamik; `import("@astro/protocol")`
olur.

- [ ] **Adım 9: Her şeyin yeşil olduğunu doğrula**

```bash
npm install
npm run typecheck
npm test
npm run build
```
Beklenen: typecheck çıktısı boş (hata yok), 22 test geçer (16 mevcut + 6 yeni
şema testi), build çalışır.

- [ ] **Adım 10: Commit**

```bash
git add -A
git commit -m "refactor(protocol): sözleşme zod şemalarına taşındı, typecheck onarıldı

shared/ klasörü @astro/protocol paketi oldu. Sözleşme artık yalnızca tip değil
çalışma zamanı doğrulaması da veriyor — ağ geçidi istemciden geleni doğrulamak
zorunda ve tipler orada işe yaramıyor.

Kökte tsconfig.json olmadığı için npm run typecheck TS5083 ile ölüyordu; proje
referanslarıyla onarıldı."
```

---

## Görev 2: `apps/gateway` — Fastify sunucusunun taşınması

**Dosyalar:**
- Taşı: `server/` → `apps/gateway/`
- Değiştir: `apps/gateway/package.json` (ad, bağımlılık)
- Değiştir: `apps/gateway/src/index.ts` (`hello` çerçevesine `v` alanı, komut doğrulama)
- Oluştur: `apps/gateway/test/command.test.ts`
- Değiştir: `tsconfig.json` (kök referansı)

**Arayüzler:**
- Tüketir: `@astro/protocol` → `commandSchema`, `serverMessageSchema`, `HEAD_YAW_LIMIT_DEG`, `PROTOCOL_VERSION`
- Üretir: `apps/gateway` çalıştırılabilir sunucu; `CLIENT_DIST` ortam değişkeniyle statik kök alır

- [ ] **Adım 1: Taşı**

```bash
mkdir -p apps
git mv server apps/gateway
```

`apps/gateway/package.json` içinde `"name": "gateway"` → `"@astro/gateway"`,
`"dependencies"` içine `"@astro/protocol": "*"` eklenir.
`apps/gateway/tsconfig.json` içindeki `"extends": "../tsconfig.base.json"` →
`"../../tsconfig.base.json"`, `"include": ["src", "test", "../../packages/protocol/src"]`.
Kök `tsconfig.json` referansı `./server` → `./apps/gateway`.
Kök `package.json` workspaces listesinden `"server"` düşer (`apps/*` kapsıyor).

- [ ] **Adım 2: Başarısız testi yaz**

`apps/gateway/test/command.test.ts`:

```ts
import { describe, expect, it } from "vitest";

import { HEAD_YAW_LIMIT_DEG } from "@astro/protocol";

import { parseCommand } from "../src/command";

describe("parseCommand", () => {
  it("geçerli komutu çözer", () => {
    expect(parseCommand(JSON.stringify({ kind: "head.center" }))).toEqual({
      ok: true,
      command: { kind: "head.center" },
    });
  });

  it("bozuk JSON'u hata olarak döner, fırlatmaz", () => {
    const sonuc = parseCommand("{bu json değil");
    expect(sonuc.ok).toBe(false);
  });

  /*
   * Sınır ihlali "kırpılarak kabul" edilmez, reddedilir. Sessizce kırpmak
   * operatöre gönderdiği komutun uygulandığını düşündürür.
   */
  it("sınır dışı açıyı reddeder", () => {
    const sonuc = parseCommand(JSON.stringify({ kind: "head.target", yawDeg: HEAD_YAW_LIMIT_DEG + 5 }));
    expect(sonuc.ok).toBe(false);
  });

  it("tanınmayan komutu reddeder", () => {
    expect(parseCommand(JSON.stringify({ kind: "dans.et" })).ok).toBe(false);
  });
});
```

- [ ] **Adım 3: Testi koş, başarısız olduğunu gör**

Çalıştır: `npm test -- apps/gateway`
Beklenen: FAIL — `Cannot find module '../src/command'`

- [ ] **Adım 4: Uygula**

`apps/gateway/src/command.ts`:

```ts
import { type Command, commandSchema } from "@astro/protocol";

export type ParseResult =
  | { ok: true; command: Command }
  | { ok: false; message: string };

/**
 * Soket üzerinden gelen ham metni komuta çevirir.
 *
 * Fırlatmaz: WebSocket dinleyicisinin içinde atılan bir hata bağlantıyı
 * düşürürdü. Hata bir değer olarak döner ve istemciye anlaşılır bir mesaj
 * gider.
 */
export function parseCommand(raw: string): ParseResult {
  let gövde: unknown;
  try {
    gövde = JSON.parse(raw);
  } catch {
    return { ok: false, message: "Komut çözümlenemedi" };
  }

  const sonuc = commandSchema.safeParse(gövde);
  if (!sonuc.success) {
    return { ok: false, message: "Komut sözleşmeye uymuyor" };
  }
  return { ok: true, command: sonuc.data };
}
```

`apps/gateway/src/index.ts` içindeki `socket.on("message", ...)` bloğu bunu
kullanacak şekilde değişir ve `hello` çerçevesi `v: PROTOCOL_VERSION` taşır.

- [ ] **Adım 5: Testi koş, geçtiğini gör**

Çalıştır: `npm test`
Beklenen: 26 test geçer

- [ ] **Adım 6: Commit**

```bash
git add -A
git commit -m "refactor(gateway): server/ apps/gateway oldu, komutlar şemayla doğrulanıyor

Komut çözümleme ayrı bir modüle çıktı ve fırlatmak yerine sonuç dönüyor:
WebSocket dinleyicisinin içinde atılan hata bağlantıyı düşürüyordu."
```

---

# Faz 1 — Kurumsal site ve SEO

## Görev 3: `apps/site` — Next.js iskeleti ve SSR içerik testi

Bu görevin tek amacı **bugünkü SEO hatasını yakalayan testi kırmızıdan yeşile
çevirmek**: ham HTML yanıtında `h1` görünmeli.

**Dosyalar:**
- Oluştur: `apps/site/package.json`, `apps/site/next.config.ts`, `apps/site/tsconfig.json`
- Oluştur: `apps/site/src/app/layout.tsx`, `apps/site/src/app/page.tsx`
- Oluştur: `apps/site/src/app/fonts.ts`
- Taşı: `client/src/styles/*.css` → `packages/ui/styles/*.css`
- Oluştur: `packages/ui/package.json`
- Taşı: `client/public/models/astro-hero.glb` → `apps/site/public/models/astro-hero.glb`
- Oluştur: `apps/site/src/data/kurum.ts`
- Oluştur: `e2e/ssr-icerik.spec.ts`, `playwright.config.ts`
- Değiştir: kök `package.json` (scriptler), `tsconfig.json` (referans)

**Arayüzler:**
- Üretir: `apps/site` Next uygulaması, `npm run dev:site` ve `npm run build:site`
- Üretir: `KURUM` sabiti — `{ unvan, kisaAd, vergiNo, adres, telefon, eposta, etbis, YER_TUTUCU: true }`
- Üretir: `packages/ui/styles/{tokens,base,layout,console}.css`

- [ ] **Adım 1: Başarısız testi yaz**

`e2e/ssr-icerik.spec.ts` — JavaScript'i **kapatarak** ham HTML'i ölçer. Bugünkü
hata tam olarak budur: JS çalışınca içerik var, çalışmayınca yok.

```ts
import { expect, test } from "@playwright/test";

/*
 * JavaScript kapalıyken ölçüyoruz.
 *
 * Bugünkü hata JS açıkken görünmüyor: tarayıcı içeriği kendisi çiziyor.
 * Arama motoru tarayıcıları ve LLM tarayıcıları çoğu zaman bunu yapmaz, bu
 * yüzden ölçüt ham yanıtın kendisidir.
 */
test.use({ javaScriptEnabled: false });

test("ana sayfa ham HTML'de başlığını ve gövde metnini taşır", async ({ page }) => {
  await page.goto("/");

  const h1 = page.locator("h1");
  await expect(h1).toHaveCount(1);
  await expect(h1).toContainText("Konuşanı duyar");

  // Gövde metni de sunucudan gelmeli, yalnızca başlık değil.
  await expect(page.getByText("kiminle ilgileneceğine kendi")).toBeVisible();
});

test("ana sayfa ölçülmüş çalışma sınırlarını metin olarak yayar", async ({ page }) => {
  await page.goto("/");
  // Bu değerler protocol paketindeki sabitlerden gelir, elle yazılmaz.
  await expect(page.getByText("±85°")).toBeVisible();
  await expect(page.getByText("121°")).toBeVisible();
});
```

`playwright.config.ts`:

```ts
import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  use: { baseURL: "http://localhost:3000" },
  webServer: {
    // Üretim çıktısına karşı koşar: dev sunucusundaki davranış farkları
    // SSR testini yalancı yeşile çevirebilir.
    command: "npm run build:site && npm run start:site",
    url: "http://localhost:3000",
    reuseExistingServer: !process.env.CI,
    timeout: 180_000,
  },
});
```

- [ ] **Adım 2: Testi koş, başarısız olduğunu gör**

Çalıştır: `npx playwright test e2e/ssr-icerik.spec.ts`
Beklenen: FAIL — `apps/site` henüz yok, sunucu ayağa kalkmaz

- [ ] **Adım 3: Next uygulamasını kur**

```bash
mkdir -p apps/site/src/app packages/ui/styles
git mv client/src/styles/tokens.css packages/ui/styles/tokens.css
git mv client/src/styles/base.css packages/ui/styles/base.css
git mv client/src/styles/layout.css packages/ui/styles/layout.css
git mv client/src/styles/console.css packages/ui/styles/console.css
mkdir -p apps/site/public/models
git mv client/public/models/astro-hero.glb apps/site/public/models/astro-hero.glb
npm install --workspace=@astro/site next@16.3.6 react@19.3.0 react-dom@19.3.0
npm install --workspace=@astro/site -D @types/react @types/react-dom
npm install -D @playwright/test@1.63.0
```

`packages/ui/package.json`:

```json
{
  "name": "@astro/ui",
  "private": true,
  "version": "0.1.0",
  "type": "module",
  "exports": { "./styles/*": "./styles/*" }
}
```

`apps/site/next.config.ts`:

```ts
import type { NextConfig } from "next";

const config: NextConfig = {
  /*
   * Tek VPS'e taşınabilirlik kararı (D4): standalone çıktı Docker imajının
   * node_modules taşımadan çalışmasını sağlar. Vercel bunu yok sayar, bedeli
   * yoktur, ve taşıma günü bunu sonradan eklemek build hattını yeniden
   * yazmak demekti.
   */
  output: "standalone",
  /* Kaynak TS olarak yayınlanan çalışma alanı paketleri Next tarafından derlenir. */
  transpilePackages: ["@astro/protocol", "@astro/ui"],
};

export default config;
```

`apps/site/src/app/fonts.ts` — yazı tipleri `next/font` ile yerelleşir; bugünkü
`<link rel="stylesheet">` fazladan bir gidiş-dönüş ve düzen kayması demek:

```ts
import { IBM_Plex_Mono, Inter, Source_Serif_4 } from "next/font/google";

/*
 * Değişken adları tokens.css içindeki --font-* belirteçleriyle eşleşir; CSS
 * tarafında tek satır değişmesin diye.
 */
export const serif = Source_Serif_4({
  subsets: ["latin", "latin-ext"],
  variable: "--font-display-loaded",
  display: "swap",
});

export const ui = Inter({
  subsets: ["latin", "latin-ext"],
  variable: "--font-ui-loaded",
  display: "swap",
});

export const mono = IBM_Plex_Mono({
  subsets: ["latin", "latin-ext"],
  weight: ["400", "500"],
  variable: "--font-mono-loaded",
  display: "swap",
});
```

`latin-ext` alt kümesi zorunlu: Türkçe ğ, ş, ı, İ, ö, ü, ç harfleri `latin`
içinde yok.

`packages/ui/styles/tokens.css` içindeki üç yazı tipi belirteci yüklenen
değişkene bağlanır:

```css
  --font-display: var(--font-display-loaded), "Georgia", "Times New Roman", serif;
  --font-ui:      var(--font-ui-loaded), system-ui, -apple-system, "Segoe UI", sans-serif;
  --font-mono:    var(--font-mono-loaded), ui-monospace, "SF Mono", Menlo, monospace;
```

`apps/site/src/app/layout.tsx`:

```tsx
import type { Metadata } from "next";

import "@astro/ui/styles/tokens.css";
import "@astro/ui/styles/base.css";
import "@astro/ui/styles/layout.css";

import { mono, serif, ui } from "./fonts";

export const metadata: Metadata = {
  title: { default: "ASTRO — sosyal robot platformu", template: "%s — ASTRO" },
  description:
    "Konuşana ve görünen kişiye dönen sosyal robot platformu. Karşılama, " +
    "bilgilendirme ve etkileşim gerektiren ortamlar için.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="tr" className={`${serif.variable} ${ui.variable} ${mono.variable}`}>
      <head>
        <meta name="color-scheme" content="dark" />
      </head>
      <body>{children}</body>
    </html>
  );
}
```

`apps/site/src/data/kurum.ts`:

```ts
/**
 * Kurum bilgileri — **YER TUTUCU** (bkz. docs/RISKLER.md R3).
 *
 * Gerçek ticari unvan, vergi numarası, adres ve ETBİS kaydı henüz verilmedi.
 * Hukuki sayfalar ve iyzico başvurusu bu değerlerle tamamlanamaz; Faz 3 bu
 * dosya gerçek bilgiyle dolmadan yayına çıkmaz.
 *
 * Değiştirilecek tek yer burasıdır.
 */
export const KURUM = {
  YER_TUTUCU: true,
  kisaAd: "ASTRO",
  unvan: "[YER TUTUCU] Barline Robotik A.Ş.",
  vergiNo: "[YER TUTUCU]",
  vergiDairesi: "[YER TUTUCU]",
  adres: "[YER TUTUCU] Türkiye",
  telefon: "[YER TUTUCU]",
  eposta: "iletisim@example.invalid",
  etbis: "[YER TUTUCU]",
  /** Canonical ve OG adresleri buradan türetilir. */
  siteUrl: process.env.NEXT_PUBLIC_SITE_URL ?? "http://localhost:3000",
  repoUrl: "https://github.com/BarlineTR/astr1",
} as const;
```

`apps/site/src/app/page.tsx` bu adımda yalnızca testi geçirecek kadar: `h1`,
giriş metni ve rakam şeridi. Metin `apps/site/src/data/icerik.ts`e taşınan
`HERO` ve `FIGURES` sabitlerinden gelir; `FIGURES` değerleri
`@astro/protocol`ten okunur:

```ts
import { AUDIO_REACHABLE_DEG, CAMERA_HFOV_DEG, HEAD_YAW_LIMIT_DEG } from "@astro/protocol";

export const FIGURES = [
  { label: "Kafa dönüş aralığı", value: `±${HEAD_YAW_LIMIT_DEG}°` },
  { label: "Kamera görüş açısı", value: `${CAMERA_HFOV_DEG}°` },
  { label: "Ulaşılabilir ses açısı", value: `${AUDIO_REACHABLE_DEG}°` },
  { label: "Etkileşim mesafesi", value: "0,4 – 2,5 m" },
] as const;
```

Kök `package.json` scriptleri:

```json
{
  "dev:site": "npm run dev --workspace=@astro/site",
  "build:site": "npm run build --workspace=@astro/site",
  "start:site": "npm run start --workspace=@astro/site",
  "e2e": "playwright test"
}
```

- [ ] **Adım 4: Testi koş, geçtiğini gör**

Çalıştır: `npx playwright test e2e/ssr-icerik.spec.ts`
Beklenen: PASS — dört iddia da geçer

- [ ] **Adım 5: Commit**

```bash
git add -A
git commit -m "feat(site): Next.js 16 iskeleti, içerik artık sunucuda üretiliyor

Bugüne kadar üretilen HTML gövdesi <div id=\"app\"></div> idi: bütün metin
tarayıcıda çiziliyordu ve arama motorları için site pratikte içeriksizdi.
Regresyon testi JavaScript kapalıyken ham yanıtı ölçüyor.

Yazı tipleri next/font ile yerelleşti — Google Fonts <link> fazladan bir
gidiş-dönüş ve düzen kaymasıydı. latin-ext alt kümesi Türkçe harfler için
zorunlu."
```

---

## Görev 4: Başlık şeridi, alt bilgi ve ana sayfanın React'e taşınması

Sahne, kaydırma anlatısı ve beliren parçalar **değiştirilmez**; React yalnızca
işaretlemeyi üretir ve bu üç modülü `useEffect` içinde sürer. Sınıf adları birebir
korunur, yoksa `layout.css` ve `showcase.ts` çalışmaz.

**Dosyalar:**
- Oluştur: `apps/site/src/components/SiteHeader.tsx`, `SiteFooter.tsx`
- Oluştur: `apps/site/src/components/HeroSahne.tsx` (istemci bileşeni)
- Oluştur: `apps/site/src/components/Gosteri.tsx` (istemci bileşeni)
- Oluştur: `apps/site/src/scene/model-source.ts`
- Taşı: `client/src/scene/*` → `apps/site/src/scene/*` (değiştirilmeden)
- Taşı: `client/src/site/showcase.ts` → `apps/site/src/site/showcase.ts`
- Taşı: `client/src/site/showcase.test.ts` → `apps/site/src/site/showcase.test.ts`
- Taşı: `client/src/site/reveal.ts` → `apps/site/src/site/reveal.ts`
- Taşı: `client/src/data/content.ts` → `apps/site/src/data/icerik.ts`
- Değiştir: `apps/site/src/app/page.tsx` (tam ana sayfa)

**Arayüzler:**
- Tüketir: `startShowcase({ scene, steps, markEl, markLabelEl, stageEl })`,
  `observeReveals(targets, reducedMotion)`, `createRobotScene(el, options)`
- Üretir: `<SiteHeader current="ana" />`, `<SiteFooter />`, `<HeroSahne />`, `<Gosteri steps={SHOWCASE} />`

- [ ] **Adım 1: Çerçeveden bağımsız modülleri taşı, testi koş**

```bash
mkdir -p apps/site/src/scene apps/site/src/site apps/site/src/data
git mv client/src/scene/robot-scene.ts apps/site/src/scene/robot-scene.ts
git mv client/src/scene/robot-model.ts apps/site/src/scene/robot-model.ts
git mv client/src/scene/bearing-ring.ts apps/site/src/scene/bearing-ring.ts
git mv client/src/scene/fov-frustum.ts apps/site/src/scene/fov-frustum.ts
git mv client/src/site/showcase.ts apps/site/src/site/showcase.ts
git mv client/src/site/showcase.test.ts apps/site/src/site/showcase.test.ts
git mv client/src/site/reveal.ts apps/site/src/site/reveal.ts
git mv client/src/data/content.ts apps/site/src/data/icerik.ts
npm install --workspace=@astro/site three@^0.170.0
npm install --workspace=@astro/site -D @types/three@^0.170.0
npm test -- apps/site
```
Beklenen: 10 `showcase` testi geçer. Bu testlerin taşımadan sağ çıkması,
kaydırma anlatısının React'ten bağımsız kaldığının kanıtıdır.

- [ ] **Adım 2: Model yolunu tek noktaya topla**

`apps/site/src/scene/model-source.ts`:

```ts
/**
 * Giriş sahnesindeki modelin adresi.
 *
 * Bu dosya bilerek tek satırdır: mevcut model geçicidir (docs/RISKLER.md R1) ve
 * gerçek ASTRO taraması geldiğinde değişmesi gereken tek yer burasıdır.
 *
 * Model değişirse kubbe dikiş yüksekliği yeniden ölçülmelidir:
 *   python3 scripts/measure-model-seam.py apps/site/public/models/astro-hero.glb
 */
export const MODEL_URL = "/models/astro-hero.glb";
```

`robot-scene.ts` içindeki gömülü model yolu bunu kullanır.

- [ ] **Adım 3: Başlık şeridini yaz**

`apps/site/src/components/SiteHeader.tsx` — mevcut `chrome.ts` ile aynı
işaretlemeyi üretir. Gezinme artık kurumsal mimariyi taşır:

```tsx
import Link from "next/link";

import { SITE } from "../data/icerik";

export type PageId =
  | "ana" | "platform" | "cozumler" | "teknoloji"
  | "fiyatlandirma" | "hakkimizda" | "iletisim" | "panel";

const NAV: Array<{ id: PageId; label: string; href: string }> = [
  { id: "platform", label: "Platform", href: "/platform" },
  { id: "cozumler", label: "Çözümler", href: "/cozumler" },
  { id: "teknoloji", label: "Teknoloji", href: "/teknoloji" },
  { id: "fiyatlandirma", label: "Fiyatlandırma", href: "/fiyatlandirma" },
  { id: "hakkimizda", label: "Hakkımızda", href: "/hakkimizda" },
];

export function SiteHeader({ current }: { current: PageId }) {
  return (
    <header className="site-header">
      <div className="page site-header__inner">
        <Link className="site-header__mark" href="/">
          {SITE.name}
          <span>{SITE.version}</span>
        </Link>
        <nav className="site-nav" aria-label="Sayfalar">
          {NAV.map((item) => (
            <Link
              key={item.id}
              href={item.href}
              className={item.id === current ? "is-current" : undefined}
              aria-current={item.id === current ? "page" : undefined}
            >
              {item.label}
            </Link>
          ))}
        </nav>
        <Link className="btn btn--quiet" href="/iletisim">
          İletişim
        </Link>
        {/* Panel gezinme bağlantısı değil, eylem: şeritte çerçeveli durur. */}
        <Link
          className={current === "panel" ? "btn btn--console is-current" : "btn btn--console"}
          href="/panel"
          aria-current={current === "panel" ? "page" : undefined}
        >
          Panel
        </Link>
      </div>
    </header>
  );
}
```

`SiteFooter.tsx` aynı desenle: telif satırı, gezinme, hukuki bağlantılar ve
`KURUM.unvan`. `KURUM.YER_TUTUCU` doğruysa alt bilgide görünür bir uyarı şeridi
çizilir — yer tutucu bilgiyle yayına çıkmayı fark etmeden yapmak mümkün olmasın:

```tsx
{KURUM.YER_TUTUCU && (
  <p className="site-footer__uyari" role="status">
    Bu sayfadaki kurum bilgileri yer tutucudur — yayına hazır değildir.
  </p>
)}
```

`packages/ui/styles/layout.css`e `.site-footer__uyari` için tek kural eklenir:
`color: var(--warn); font-family: var(--font-mono); font-size: var(--t-micro);`

- [ ] **Adım 4: Giriş sahnesini istemci bileşeni yap**

`apps/site/src/components/HeroSahne.tsx`. Açılış evrelerinin sınıf değiştirmesi
imperatif kalır: durumu React'e taşımak CSS geçişlerinin sırasını değiştirir ve
`entries/home.ts` içindeki ölçülmüş zamanlama (1800 ms bekleme, `--intro-exit`)
yeniden ayarlanmak zorunda kalırdı.

```tsx
"use client";

import { useEffect, useRef } from "react";

import { INTRO } from "../data/icerik";

export function HeroSahne({ heroRef }: { heroRef: React.RefObject<HTMLElement | null> }) {
  const stageRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const stage = stageRef.current;
    const hero = heroRef.current;
    if (!stage || !hero) return;

    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    let iptal = false;
    let sahne: { stop?: () => void } | null = null;

    const evre = (ad: "intro" | "exiting" | "settled"): void => {
      hero.classList.toggle("is-intro", ad === "intro");
      hero.classList.toggle("is-exiting", ad === "exiting");
      hero.classList.toggle("is-settled", ad === "settled");
    };

    /*
     * Açılış sırası sahneyi beklemez: model geç yüklense de metin zamanında
     * gelir. İkisi aynı anda görünseydi dev tipografi modelin üstüne binerdi.
     */
    const INTRO_HOLD_MS = 1800;
    const cikisSuresi = parseFloat(
      getComputedStyle(document.documentElement).getPropertyValue("--intro-exit"),
    );
    let zamanlayici = 0;
    let bitti = false;

    const bitir = (): void => {
      if (bitti) return;
      bitti = true;
      clearTimeout(zamanlayici);
      window.removeEventListener("scroll", kaydirmaylaAtla);
      document.removeEventListener("visibilitychange", gizlenmisseAtla);
      evre("settled");
    };
    const kaydirmaylaAtla = (): void => { if (window.scrollY > 24) bitir(); };
    const gizlenmisseAtla = (): void => { if (document.hidden) bitir(); };

    if (reducedMotion || document.hidden || window.scrollY > 24 || window.location.hash) {
      bitir();
    } else {
      window.addEventListener("scroll", kaydirmaylaAtla, { passive: true });
      document.addEventListener("visibilitychange", gizlenmisseAtla);
      zamanlayici = window.setTimeout(() => {
        evre("exiting");
        zamanlayici = window.setTimeout(bitir, cikisSuresi);
      }, INTRO_HOLD_MS);
    }

    void (async () => {
      try {
        const [{ createRobotScene }, { DemoDriver }] = await Promise.all([
          import("../scene/robot-scene"),
          import("@astro/protocol"),
        ]);
        if (iptal) return;
        const s = await createRobotScene(stage, { compactLift: false });
        s.setDriver(new DemoDriver());
        s.start();
        sahne = s;
      } catch (hata) {
        console.error("Giriş sahnesi yüklenemedi:", hata);
        stage.querySelector("canvas")?.remove();
        stage.insertAdjacentHTML(
          "beforeend",
          '<div class="stage-fallback"><p class="eyebrow">3B görünüm kullanılamıyor</p>' +
            "<p>Sayfanın geri kalanı etkilenmez.</p></div>",
        );
        bitir();
      }
    })();

    return () => {
      iptal = true;
      bitir();
      sahne?.stop?.();
    };
  }, [heroRef]);

  return (
    <>
      <div className="hero__stage" ref={stageRef} />
      <div className="intro" aria-hidden="true">
        <p className="intro__line">
          <span className="intro__kicker">{INTRO.kicker}</span>
          <span className="intro__name">{INTRO.name}</span>
        </p>
        <p className="intro__tail">{INTRO.tail}</p>
      </div>
    </>
  );
}
```

**Kritik:** `hero__inner` bloğu sunucuda çizilir ve `intro` evresindeyken
`inert` olmalıdır (görünmeyen bir bağlantıya sekmeyle ulaşmak odağı kaybettirir).
Bu, `HeroSahne` içindeki `evre()` fonksiyonuna eklenir:
`hero.querySelector(".hero__inner")?.toggleAttribute("inert", ad !== "settled")`.

- [ ] **Adım 5: Gösteri bölümünü istemci bileşeni yap**

`apps/site/src/components/Gosteri.tsx`. Adım metinleri **sunucuda** çizilir —
SEO'nun asıl kazandığı yer burasıdır, altı özelliğin tamamı ham HTML'de bulunur.
İstemci yalnızca sahneyi kurar ve `startShowcase`e elementleri verir.

```tsx
"use client";

import { useEffect, useRef } from "react";

import { SHOWCASE } from "../data/icerik";

export function Gosteri() {
  const bolumRef = useRef<HTMLElement>(null);
  const stageRef = useRef<HTMLDivElement>(null);
  const markRef = useRef<HTMLDivElement>(null);
  const markLabelRef = useRef<HTMLSpanElement>(null);
  const stepRefs = useRef<Array<HTMLLIElement | null>>([]);

  useEffect(() => {
    const bolum = bolumRef.current;
    const stage = stageRef.current;
    const markEl = markRef.current;
    const markLabelEl = markLabelRef.current;
    const steps = stepRefs.current.filter((x): x is HTMLLIElement => x !== null);
    if (!bolum || !stage || !markEl || !markLabelEl || steps.length === 0) return;

    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    if (!("ResizeObserver" in window) || !("IntersectionObserver" in window)) return;

    let kontrol: { stop(): void } | null = null;
    let iptal = false;

    /*
     * İki sahne iki WebGL bağlamı demek. Ziyaretçi giriş ekranından ayrılmadan
     * çıkarsa ikinci bağlam hiç açılmasın; yüklemeye bölüm ekrana girmeden
     * başlanır ki oraya varıldığında hazır olsun.
     */
    const gozlemci = new IntersectionObserver(
      (girisler) => {
        if (!girisler.some((g) => g.isIntersecting)) return;
        gozlemci.disconnect();
        void (async () => {
          try {
            const [{ createRobotScene }, { startShowcase }] = await Promise.all([
              import("../scene/robot-scene"),
              import("../site/showcase"),
            ]);
            if (iptal) return;
            const sahne = await createRobotScene(stage, {
              autoOrbit: false,
              interactive: false,
              compactLift: false,
            });
            sahne.start();
            kontrol = startShowcase({ scene: sahne, steps, markEl, markLabelEl, stageEl: stage });
          } catch (hata) {
            console.error("Gösteri sahnesi yüklenemedi:", hata);
          }
        })();
      },
      { rootMargin: "120% 0px" },
    );
    gozlemci.observe(bolum);

    return () => {
      iptal = true;
      gozlemci.disconnect();
      kontrol?.stop();
    };
  }, []);

  return (
    <section className="showcase" ref={bolumRef}>
      <div className="showcase__sticky">
        <div className="showcase__stage" ref={stageRef} />
        <div className="mark" aria-hidden="true" ref={markRef}>
          <span className="mark__ring" />
          <span className="mark__stem" />
          <span className="mark__label" ref={markLabelRef} />
        </div>
      </div>
      <ol className="showcase__steps">
        {SHOWCASE.map((step, i) => (
          <li
            key={step.id}
            className="step"
            id={i === 0 ? "ozellikler" : step.id}
            ref={(el) => { stepRefs.current[i] = el; }}
          >
            <div className="page step__inner">
              <p className="step__index mono">
                {String(i + 1).padStart(2, "0")} / {String(SHOWCASE.length).padStart(2, "0")}
              </p>
              <h2 className="step__title">{step.title}</h2>
              <p className="step__body">{step.body}</p>
            </div>
          </li>
        ))}
      </ol>
    </section>
  );
}
```

- [ ] **Adım 6: Ana sayfayı birleştir, e2e testini koş**

`apps/site/src/app/page.tsx` sunucu bileşeni olarak `SiteHeader`, hero kabuğu
(içinde `HeroSahne`), `Gosteri`, diğer yetenekler ve kapanış bölümünü çizer.
Hero kabuğunun `ref`e ihtiyacı olduğu için ince bir istemci sarmalayıcı
(`HeroBolum.tsx`) `heroRef`i tutar; içindeki metin `children` olarak sunucudan
gelir, yani SSR'da görünür.

Çalıştır: `npx playwright test`
Beklenen: PASS

Çalıştır: `npm test`
Beklenen: 26 test geçer (10 showcase testi taşındıktan sonra da yeşil)

- [ ] **Adım 7: Commit**

```bash
git add -A
git commit -m "feat(site): ana sayfa React'e taşındı, sahne ve anlatı dokunulmadı

three.js sahnesi, kaydırma anlatısı ve beliren parçalar çerçeveden bağımsız
olduğu için hiç değişmedi; React yalnızca işaretlemeyi üretiyor ve bu üç modülü
useEffect içinde sürüyor. showcase.ts'in 10 testi taşımadan sonra da geçiyor —
ayrımın gerçekten temiz olduğunun kanıtı.

Açılış evrelerinin sınıf değiştirmesi bilerek imperatif kaldı: React durumuna
taşımak ölçülmüş zamanlamayı (1800 ms + --intro-exit) yeniden ayarlamak
demekti.

Altı özellik adımının metni artık sunucuda çiziliyor."
```

---

## Görev 5: Hakkımızda, yönetim ve basın sayfaları

**Dosyalar:**
- Oluştur: `apps/site/src/app/hakkimizda/page.tsx`
- Oluştur: `apps/site/src/app/hakkimizda/yonetim/page.tsx`
- Oluştur: `apps/site/src/app/basin/page.tsx`
- Oluştur: `apps/site/src/data/kurumsal.ts` (yönetim + basın içeriği, yer tutucu)
- Sil: `client/src/pages/about.ts`, `client/src/entries/about.ts`, `client/hakkimizda.html`

**Arayüzler:**
- Tüketir: `ABOUT` (mevcut `icerik.ts`), `KURUM`
- Üretir: `YONETIM` (ad, unvan, kısa tanıtım — yer tutucu), `BASIN` (varlık listesi)

- [ ] **Adım 1: Yer tutucu içeriği yaz**

`apps/site/src/data/kurumsal.ts`. Mevcut `ABOUT` metninin erdemi korunur:
**doğrulanamaz iddia içermez**. Yönetim listesi de aynı kuralla yazılır — uydurma
isim konmaz, yapı konur ve boş olduğu görünür.

```ts
/**
 * Yönetim ekibi — **YER TUTUCU** (docs/RISKLER.md R3).
 *
 * Uydurma isim konmadı. Liste boş geldiğinde sayfa "bilgi yakında" der; yanlış
 * bir isim yazmaktan iyidir ve boş kalması gerçek bilginin eksik olduğunu
 * görünür kılar.
 */
export const YONETIM: ReadonlyArray<{
  ad: string;
  unvan: string;
  tanitim: string;
}> = [];

export const BASIN = {
  lead:
    "Basın mensupları ve iş ortaklarımız için marka varlıkları ve kurumsal " +
    "künye bilgileri.",
  varliklar: [
    { ad: "ASTRO logo (SVG)", href: "/basin/astro-logo.svg", not: "Koyu zemin için" },
    { ad: "Platform görseli (PNG)", href: "/basin/astro-platform.png", not: "3000 px genişlik" },
  ],
} as const;
```

- [ ] **Adım 2: Başarısız testi yaz**

`e2e/kurumsal-sayfalar.spec.ts`:

```ts
import { expect, test } from "@playwright/test";

test.use({ javaScriptEnabled: false });

const sayfalar = [
  { yol: "/hakkimizda", baslik: "Hakkımızda" },
  { yol: "/hakkimizda/yonetim", baslik: "Yönetim" },
  { yol: "/basin", baslik: "Basın" },
  { yol: "/platform", baslik: "Platform" },
  { yol: "/teknoloji", baslik: "Teknoloji" },
  { yol: "/fiyatlandirma", baslik: "Fiyatlandırma" },
  { yol: "/iletisim", baslik: "İletişim" },
];

for (const sayfa of sayfalar) {
  test(`${sayfa.yol} ham HTML'de tek bir h1 taşır`, async ({ page }) => {
    const yanit = await page.goto(sayfa.yol);
    expect(yanit?.status()).toBe(200);
    const h1 = page.locator("h1");
    await expect(h1).toHaveCount(1);
    await expect(h1).toContainText(sayfa.baslik);
  });
}

test("yer tutucu kurum bilgisi alt bilgide görünür uyarı üretir", async ({ page }) => {
  await page.goto("/hakkimizda");
  await expect(page.getByText("kurum bilgileri yer tutucudur")).toBeVisible();
});
```

- [ ] **Adım 3: Testi koş, başarısız olduğunu gör**

Çalıştır: `npx playwright test e2e/kurumsal-sayfalar.spec.ts`
Beklenen: FAIL — yedi yolun hepsi 404

- [ ] **Adım 4: Üç sayfayı yaz**

`hakkimizda/page.tsx` mevcut `ABOUT.sections` yapısını numaralı bölüm iskeletiyle
çizer (eski `dom.ts` içindeki `section()` deseninin React karşılığı:
`.section` > `.page` > `.section__head` > `.section__index` + başlık).
`yonetim/page.tsx` liste boşsa "Bilgi yakında eklenecek" der.
`basin/page.tsx` varlıkları indirme listesi olarak çizer.

- [ ] **Adım 5: Testi koş** (Görev 6'daki sayfalar hâlâ 404 vereceği için bu adımda
      yalnızca üç hakkımızda/basın testi geçer; `--grep` ile daraltılır)

Çalıştır: `npx playwright test e2e/kurumsal-sayfalar.spec.ts --grep "hakkimizda|basin|yer tutucu"`
Beklenen: PASS

- [ ] **Adım 6: Eski Vite sayfalarını sil ve commit**

```bash
git rm client/src/pages/about.ts client/src/entries/about.ts client/hakkimizda.html
git add -A
git commit -m "feat(site): hakkımızda, yönetim ve basın sayfaları

Yönetim listesi bilerek boş: uydurma isim yazmak yerine sayfa 'yakında' diyor,
böylece eksik bilgi görünür kalıyor. Mevcut hakkımızda metninin doğrulanamaz
iddia içermeme erdemi korundu."
```

---

## Görev 6: Kurumsal ürün mimarisi — platform, çözümler, teknoloji, fiyatlandırma

**Dosyalar:**
- Oluştur: `apps/site/src/app/platform/page.tsx`
- Oluştur: `apps/site/src/app/cozumler/page.tsx`
- Oluştur: `apps/site/src/app/cozumler/[sektor]/page.tsx`
- Oluştur: `apps/site/src/app/teknoloji/page.tsx`
- Oluştur: `apps/site/src/app/fiyatlandirma/page.tsx`
- Oluştur: `apps/site/src/data/cozumler.ts`, `apps/site/src/data/fiyatlar.ts`
- Oluştur: `apps/site/src/components/TeknikTablo.tsx`

**Arayüzler:**
- Üretir: `COZUMLER` — `Array<{ slug, ad, ozet, senaryo[], kazanc[] }>`
- Üretir: `PLANLAR` — `Array<{ slug, ad, aciklama, fiyatKurus, periyot, ozellikler[] }>`
  ve `DESTEK_PAKETLERI` — aynı biçim, `periyot: "tek"`
- Üretir: `GELISTIRME_FIYATI: true` sabiti

- [ ] **Adım 1: Fiyat verisini yaz (uydurma, işaretli)**

`apps/site/src/data/fiyatlar.ts`:

```ts
/**
 * Fiyatlar — **GELİŞTİRME DEĞERLERİ** (docs/RISKLER.md R4).
 *
 * Gerçek fiyat listesi verilmedi. Buradaki tutarlar akışı uçtan uca
 * çalıştırabilmek için uydurulmuştur ve ödeme akışı bu bayrak kalkmadan yayına
 * alınmaz.
 *
 * Tutarlar tam sayı kuruştur. Para hiçbir yerde kayan noktayla tutulmaz:
 * 199,90 TL → 19990.
 */
export const GELISTIRME_FIYATI = true;

export const DESTEK_PAKETLERI = [
  { slug: "cay", ad: "Çay", aciklama: "Küçük bir teşekkür.", fiyatKurus: 5000, periyot: "tek" },
  { slug: "kahve", ad: "Kahve", aciklama: "Bir sonraki prototipin lehimine.", fiyatKurus: 15000, periyot: "tek" },
  { slug: "devre", ad: "Devre", aciklama: "Bir sensör kartı kadar destek.", fiyatKurus: 50000, periyot: "tek" },
] as const;

export const PLANLAR = [
  {
    slug: "gozlem",
    ad: "Gözlem",
    aciklama: "Tek robot, telemetri izleme.",
    fiyatKurus: 49900,
    periyot: "ay",
    ozellikler: ["1 robot", "Canlı telemetri", "30 gün kayıt geçmişi"],
  },
  {
    slug: "operasyon",
    ad: "Operasyon",
    aciklama: "Uzaktan kontrol ve teşhis.",
    fiyatKurus: 149900,
    periyot: "ay",
    ozellikler: ["5 robota kadar", "Uzaktan kontrol", "Log ve teşhis erişimi", "Öncelikli destek"],
  },
] as const;
```

- [ ] **Adım 2: Başarısız testi yaz**

`apps/site/src/data/fiyatlar.test.ts`:

```ts
import { describe, expect, it } from "vitest";

import { DESTEK_PAKETLERI, PLANLAR } from "./fiyatlar";
import { kurusBicimle } from "../lib/para";

describe("kurusBicimle", () => {
  it("kuruşu Türk lirası olarak yazar", () => {
    expect(kurusBicimle(19990)).toBe("199,90 ₺");
  });

  it("tam liraya kuruş basamağı ekler", () => {
    expect(kurusBicimle(50000)).toBe("500,00 ₺");
  });

  /* Kayan nokta ile para tutulmadığının testi: girdi tam sayı olmalı. */
  it("tam sayı olmayan girdiyi reddeder", () => {
    expect(() => kurusBicimle(199.9)).toThrow();
  });
});

describe("fiyat verisi", () => {
  it("bütün tutarlar tam sayı kuruştur", () => {
    for (const kalem of [...DESTEK_PAKETLERI, ...PLANLAR]) {
      expect(Number.isInteger(kalem.fiyatKurus)).toBe(true);
      expect(kalem.fiyatKurus).toBeGreaterThan(0);
    }
  });

  it("slug'lar tekildir", () => {
    const slugs = [...DESTEK_PAKETLERI, ...PLANLAR].map((k) => k.slug);
    expect(new Set(slugs).size).toBe(slugs.length);
  });
});
```

- [ ] **Adım 3: Testi koş, başarısız olduğunu gör**

Çalıştır: `npm test -- apps/site/src/data`
Beklenen: FAIL — `Cannot find module '../lib/para'`

- [ ] **Adım 4: Para yardımcısını yaz**

`apps/site/src/lib/para.ts`:

```ts
/**
 * Kuruşu görüntülenecek metne çevirir.
 *
 * Girdinin tam sayı olmasını zorlar. Kayan noktalı bir tutar buraya kadar
 * geldiyse yukarıda bir yerde para bozulmuş demektir ve sessizce yuvarlamak
 * o hatayı gizler.
 */
export function kurusBicimle(kurus: number, paraBirimi = "TRY"): string {
  if (!Number.isInteger(kurus)) {
    throw new TypeError(`Tutar tam sayı kuruş olmalı, alınan: ${kurus}`);
  }
  return new Intl.NumberFormat("tr-TR", {
    style: "currency",
    currency: paraBirimi,
  }).format(kurus / 100);
}
```

- [ ] **Adım 5: Testi koş, geçtiğini gör**

Çalıştır: `npm test -- apps/site/src/data`
Beklenen: PASS (5 test)

- [ ] **Adım 6: Dört sayfayı yaz**

- `/platform`: ürün anlatısı, `TeknikTablo` ile ölçülmüş değerler (gerçek
  `<table>` olarak — üretken arama araçları tabloyu okur), `/platform/demo`ya
  bağlantı.
- `/cozumler`: sektör kartları, her biri `/cozumler/[sektor]`e gider.
  `generateStaticParams` ile üç sektör statik üretilir.
- `/teknoloji`: algı, sosyal bakış, güvenlik katmanları. Her iddianın yanında
  nereden ölçüldüğü yazılır (bu depoda zaten kural).
- `/fiyatlandirma`: `PLANLAR` ve `DESTEK_PAKETLERI`. `GELISTIRME_FIYATI` doğruysa
  sayfanın üstünde görünür bir şerit: "Fiyatlar geliştirme aşaması değerleridir."

`TeknikTablo.tsx` değerleri `@astro/protocol` sabitlerinden okur; elle yazılan
sayı olmaz.

- [ ] **Adım 7: e2e testini koş, commit**

Çalıştır: `npx playwright test e2e/kurumsal-sayfalar.spec.ts`
Beklenen: PASS (yedi sayfanın hepsi) — `/iletisim` Görev 14'e kadar iskelet
olarak var olur, bu yüzden bu görevde basit bir sayfa olarak eklenir.

```bash
git add -A
git commit -m "feat(site): platform, çözümler, teknoloji ve fiyatlandırma sayfaları

Kurumsal ürün hiyerarşisi: platform → çözüm → teknoloji → fiyat. Teknik
değerler @astro/protocol sabitlerinden okunuyor, elle yazılmıyor; ölçüm
değiştiğinde site kendiliğinde doğru kalır.

Fiyatlar uydurma ve GELISTIRME_FIYATI ile işaretli, sayfada da görünür şerit
var. Tutarlar tam sayı kuruş; kurusBicimle kayan noktalı girdiyi reddediyor."
```

---

## Görev 7: SEO — metadata, sitemap, robots, JSON-LD, OG

**Dosyalar:**
- Oluştur: `apps/site/src/app/sitemap.ts`, `apps/site/src/app/robots.ts`
- Oluştur: `apps/site/src/app/opengraph-image.tsx`
- Oluştur: `apps/site/src/lib/seo.ts`
- Oluştur: `apps/site/src/lib/seo.test.ts`
- Oluştur: `apps/site/src/components/JsonLd.tsx`
- Değiştir: bütün `page.tsx` dosyaları (`metadata` / `generateMetadata`)
- Oluştur: `e2e/seo.spec.ts`

**Arayüzler:**
- Üretir: `sayfaMetadata({ baslik, aciklama, yol })` → `Metadata`
- Üretir: `organizationJsonLd()`, `productJsonLd()`, `breadcrumbJsonLd(parcalar)`,
  `faqJsonLd(sorular)`
- Üretir: `SAYFALAR` — sitemap ve kırıntı üretiminin tek kaynağı

- [ ] **Adım 1: Başarısız testi yaz**

`apps/site/src/lib/seo.test.ts`:

```ts
import { describe, expect, it } from "vitest";

import { SAYFALAR, breadcrumbJsonLd, organizationJsonLd, sayfaMetadata } from "./seo";

describe("sayfaMetadata", () => {
  it("canonical adresi mutlak üretir", () => {
    const m = sayfaMetadata({ baslik: "Platform", aciklama: "x", yol: "/platform" });
    expect(m.alternates?.canonical).toMatch(/^https?:\/\/.+\/platform$/);
  });

  /* Ana sayfanın canonical'ı sonunda eğik çizgi taşımaz: iki adres tek sayfa demek. */
  it("ana sayfa canonical'ı çift adres üretmez", () => {
    const m = sayfaMetadata({ baslik: "ASTRO", aciklama: "x", yol: "/" });
    expect(m.alternates?.canonical).not.toMatch(/\/$/);
  });

  it("OG başlığı ve açıklaması doldurulur", () => {
    const m = sayfaMetadata({ baslik: "Teknoloji", aciklama: "ölçüm", yol: "/teknoloji" });
    expect(m.openGraph?.title).toContain("Teknoloji");
    expect(m.openGraph?.description).toBe("ölçüm");
  });
});

describe("SAYFALAR", () => {
  it("her kayıt tekil bir yol taşır", () => {
    const yollar = SAYFALAR.map((s) => s.yol);
    expect(new Set(yollar).size).toBe(yollar.length);
  });

  /*
   * Panel ve kimlik sayfaları sitemap'e girmez: giriş arkasındaki bir adresi
   * arama motoruna vermek hem işe yaramaz hem de kapıyı ilan eder.
   */
  it("giriş arkasındaki sayfalar sitemap dışıdır", () => {
    for (const sayfa of SAYFALAR.filter((s) => s.sitemap)) {
      expect(sayfa.yol.startsWith("/panel")).toBe(false);
      expect(["/giris", "/kayit"]).not.toContain(sayfa.yol);
    }
  });
});

describe("organizationJsonLd", () => {
  it("şema tipini ve adı taşır", () => {
    const ld = organizationJsonLd();
    expect(ld["@type"]).toBe("Organization");
    expect(ld.name).toBeTruthy();
  });
});

describe("breadcrumbJsonLd", () => {
  it("sırayı 1'den başlatır", () => {
    const ld = breadcrumbJsonLd([
      { ad: "Ana sayfa", yol: "/" },
      { ad: "Platform", yol: "/platform" },
    ]);
    expect(ld.itemListElement[0].position).toBe(1);
    expect(ld.itemListElement[1].position).toBe(2);
  });
});
```

- [ ] **Adım 2: Testi koş, başarısız olduğunu gör**

Çalıştır: `npm test -- apps/site/src/lib`
Beklenen: FAIL — `Cannot find module './seo'`

- [ ] **Adım 3: `seo.ts`yi yaz**

`SAYFALAR` listesi tek kaynaktır: `sitemap.ts` onu okur, kırıntılar onu okur,
`robots.ts` giriş arkasındakileri ondan çıkarır. İki yerde tutulan bir sayfa
listesi kaçınılmaz olarak ayrışır.

- [ ] **Adım 4: Testi koş, geçtiğini gör**

Çalıştır: `npm test -- apps/site/src/lib`
Beklenen: PASS (7 test)

- [ ] **Adım 5: sitemap, robots, OG görseli ve JSON-LD'yi bağla**

`app/sitemap.ts` `SAYFALAR`dan üretir. `app/robots.ts` `/panel/`, `/giris`,
`/kayit`, `/api/` yollarını yasaklar ve sitemap adresini verir.
`app/opengraph-image.tsx` Next'in `ImageResponse`u ile 1200×630 görsel üretir:
siyah zemin, pirinç çizgi, ürün adı. Ayrı bir görsel dosyası tutmak, marka
değiştiğinde güncellenmeyen bir kopya demek.

`JsonLd.tsx`:

```tsx
/**
 * JSON-LD'yi script etiketine gömer.
 *
 * `JSON.stringify` çıktısındaki `<` karakteri kaçırılır: veri içinde `</script>`
 * geçen bir metin sayfayı kırar ve bu bir enjeksiyon yoludur.
 */
export function JsonLd({ data }: { data: Record<string, unknown> }) {
  const govde = JSON.stringify(data).replace(/</g, "\\u003c");
  return <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: govde }} />;
}
```

- [ ] **Adım 6: e2e SEO testini yaz ve koş**

`e2e/seo.spec.ts`: `robots.txt` 200 döner ve `/panel/` yasaklı; `sitemap.xml`
200 döner ve `/platform` içerir; ana sayfa tek canonical taşır; `Organization`
JSON-LD geçerli JSON'dur.

Çalıştır: `npx playwright test e2e/seo.spec.ts`
Beklenen: PASS

- [ ] **Adım 7: Commit**

```bash
git add -A
git commit -m "feat(site): SEO temeli — metadata, sitemap, robots, JSON-LD, OG

Sayfa listesi tek kaynakta (SAYFALAR): sitemap, kırıntılar ve robots aynı
listeyi okuyor. İki yerde tutulan bir liste kaçınılmaz olarak ayrışıyordu.

Giriş arkasındaki adresler sitemap dışında ve robots'ta yasaklı — arama
motoruna vermek işe yaramadığı gibi kapıyı ilan ediyor.

JSON-LD gövdesinde < kaçırılıyor: veri içinde </script> geçen bir metin
sayfayı kırardı."
```

---

## Görev 8: Vite istemcisinin kaldırılması ve dağıtım ayarı

**Dosyalar:**
- Sil: `client/` (tamamı)
- Değiştir: `vercel.json`
- Değiştir: kök `package.json`, `tsconfig.json`
- Değiştir: `apps/gateway/src/index.ts` (statik servis Next'e devredildiği için kaldırılır)
- Değiştir: `README.md`

- [ ] **Adım 1: Kalan bağımlılığı doğrula**

```bash
grep -rn "client/" --include="*.ts" --include="*.tsx" --include="*.json" \
  apps packages vercel.json package.json | grep -v node_modules
```
Beklenen: yalnızca `vercel.json` ve kök `package.json` çıkar. Başka bir dosya
çıkıyorsa silmeden önce o bağ kesilir.

- [ ] **Adım 2: Sil ve dağıtımı güncelle**

```bash
git rm -r client
```

`vercel.json`:

```json
{
  "$schema": "https://openapi.vercel.sh/vercel.json",
  "buildCommand": "npm run build:site",
  "framework": "nextjs",
  "installCommand": "npm install"
}
```

`outputDirectory`, `cleanUrls` ve önbellek başlıkları kaldırılır: Next bunların
hepsini kendisi yönetir ve elle konan başlık onunla çatışır.

Ağ geçidi artık statik dosya servis etmez — `@fastify/static` ve `findClientDist`
kaldırılır. Sunucunun tek işi `/ws` ve `/saglik`.

- [ ] **Adım 3: Her şeyi doğrula**

```bash
npm install
npm run typecheck
npm test
npm run build:site
npx playwright test
```
Beklenen: hepsi yeşil.

- [ ] **Adım 4: README'yi güncelle ve commit**

```bash
git add -A
git commit -m "chore(site): Vite istemcisi kaldırıldı, dağıtım Next'e geçti

client/ tamamen Next uygulamasına taşındığı için silindi. vercel.json'daki
elle konan önbellek başlıkları ve cleanUrls da kalktı: Next bunları kendisi
yönetiyor ve ikisi çatışıyordu.

Ağ geçidi artık statik dosya servis etmiyor; tek işi /ws ve /saglik."
```

---

# Faz 2 — Kimlik, giriş/çıkış ve panel kapısı

## Görev 9: Postgres, Drizzle ve şema

**Dosyalar:**
- Oluştur: `docker/compose.yaml`
- Oluştur: `apps/site/src/db/index.ts`, `apps/site/src/db/schema.ts`
- Oluştur: `apps/site/drizzle.config.ts`
- Oluştur: `apps/site/src/db/schema.test.ts`
- Oluştur: `.env.example`
- Değiştir: `.gitignore` (`.env`, `.env.local`)

**Arayüzler:**
- Üretir: `db` — Drizzle istemcisi
- Üretir: tablolar `users`, `sessions`, `accounts`, `verifications`, `consents`,
  `contactRequests`, `devices`, `deviceGrants`, `auditEvents`
- Üretir: `ROLLER` — `["customer", "operator", "admin"]`

- [ ] **Adım 1: Postgres'i ayağa kaldır**

`docker/compose.yaml`:

```yaml
services:
  db:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: astro
      POSTGRES_PASSWORD: astro
      POSTGRES_DB: astro
    ports: ["5433:5432"]
    volumes: ["astro-db:/var/lib/postgresql/data"]
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U astro"]
      interval: 5s
      retries: 10

volumes:
  astro-db:
```

5433 kullanılır: geliştirme makinesinde 5432'de başka bir Postgres olabilir ve
sessizce yanlış veritabanına bağlanmak, bağlanamamaktan çok daha kötüdür.

```bash
docker compose -f docker/compose.yaml up -d
docker compose -f docker/compose.yaml ps
```
Beklenen: `db` servisi `healthy`.

- [ ] **Adım 2: Başarısız testi yaz**

`apps/site/src/db/schema.test.ts` — şemanın *şeklini* doğrular; veritabanı
gerektirmez, bu yüzden CI'da da koşar:

```ts
import { getTableColumns } from "drizzle-orm";
import { describe, expect, it } from "vitest";

import { auditEvents, consents, deviceGrants, devices, users } from "./schema";

describe("users", () => {
  it("rol alanı taşır", () => {
    expect(getTableColumns(users)).toHaveProperty("role");
  });

  it("e-posta tekildir", () => {
    expect(getTableColumns(users).email.isUnique).toBe(true);
  });
});

describe("consents", () => {
  /*
   * KVKK: kimin neyi hangi metin sürümünde onayladığı sonradan gösterilebilmeli.
   * Metin sürümü tutulmazsa onay ispatlanamaz.
   */
  it("onaylanan metnin sürümünü tutar", () => {
    expect(getTableColumns(consents)).toHaveProperty("textVersion");
  });

  it("girişten önce verilen onayı da tutabilir", () => {
    expect(getTableColumns(consents).userId.notNull).toBe(false);
  });
});

describe("devices", () => {
  it("jetonun kendisini değil özetini tutar", () => {
    const kolonlar = getTableColumns(devices);
    expect(kolonlar).toHaveProperty("tokenHash");
    expect(kolonlar).not.toHaveProperty("token");
  });
});

describe("deviceGrants", () => {
  it("cihaz yetkisini rolden ayrı tutar", () => {
    expect(getTableColumns(deviceGrants)).toHaveProperty("role");
  });
});

describe("auditEvents", () => {
  it("aktör ve cihaz alanları boş olabilir", () => {
    const kolonlar = getTableColumns(auditEvents);
    expect(kolonlar.actorUserId.notNull).toBe(false);
    expect(kolonlar.deviceId.notNull).toBe(false);
  });
});
```

- [ ] **Adım 3: Testi koş, başarısız olduğunu gör**

Çalıştır: `npm test -- apps/site/src/db`
Beklenen: FAIL — `Cannot find module './schema'`

- [ ] **Adım 4: Şemayı yaz**

```bash
npm install --workspace=@astro/site drizzle-orm@0.45.3 pg@8.23.0
npm install --workspace=@astro/site -D drizzle-kit@0.31.11 @types/pg
```

`apps/site/src/db/schema.ts` — spec §7'deki tabloların Drizzle karşılığı.
`auditEvents` yalnızca ekleme içindir; güncelleme ve silme yolu kodda hiç
yazılmaz (`updatedAt` kolonu bilerek yok — olması, güncellenmesini davet eder).

- [ ] **Adım 5: Testi koş, göçü uygula**

```bash
npm test -- apps/site/src/db
npx drizzle-kit generate --config apps/site/drizzle.config.ts
npx drizzle-kit migrate --config apps/site/drizzle.config.ts
```
Beklenen: testler geçer, göç dosyası `apps/site/drizzle/` altında oluşur ve
uygulanır.

- [ ] **Adım 6: Commit**

```bash
git add -A
git commit -m "feat(db): Postgres, Drizzle ve kimlik/denetim şeması

Cihaz jetonunun kendisi değil özeti saklanıyor. Onay kayıtları onaylanan metnin
sürümünü tutuyor — sürüm olmadan KVKK onayı sonradan ispatlanamaz.

auditEvents'te bilerek updatedAt yok: olması güncellenmesini davet ederdi ve
denetim kaydı yalnızca eklenir.

Postgres 5433'te: geliştirme makinesinde 5432'de başka bir örnek olabilir ve
sessizce yanlış veritabanına bağlanmak bağlanamamaktan kötüdür."
```

---

## Görev 10: better-auth, kayıt, giriş ve çıkış

**Dosyalar:**
- Oluştur: `apps/site/src/lib/auth.ts`, `apps/site/src/lib/auth-client.ts`
- Oluştur: `apps/site/src/app/api/auth/[...all]/route.ts`
- Oluştur: `apps/site/src/app/giris/page.tsx`, `GirisFormu.tsx`
- Oluştur: `apps/site/src/app/kayit/page.tsx`, `KayitFormu.tsx`
- Oluştur: `apps/site/src/components/CikisDugmesi.tsx`
- Oluştur: `packages/ui/styles/form.css`
- Oluştur: `e2e/kimlik.spec.ts`

**Arayüzler:**
- Üretir: `auth` (sunucu), `authClient` (istemci: `signIn`, `signUp`, `signOut`, `useSession`)
- Üretir: `oturumAl()` → `{ user, session } | null` — sunucu bileşenleri için

- [ ] **Adım 1: Başarısız e2e testini yaz**

`e2e/kimlik.spec.ts`:

```ts
import { expect, test } from "@playwright/test";

/** Her koşu kendi kullanıcısını yaratır; testler birbirinin durumuna binmez. */
function testKullanicisi() {
  const n = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
  return { email: `test-${n}@example.invalid`, password: "Gecici-Parola-123", name: "Test Kullanıcı" };
}

test("anonim ziyaretçi panele giremez ve girişe yönlenir", async ({ page }) => {
  await page.goto("/panel");
  await expect(page).toHaveURL(/\/giris/);
});

test("kayıt, giriş ve çıkış çalışır", async ({ page }) => {
  const k = testKullanicisi();

  await page.goto("/kayit");
  await page.getByLabel("Ad soyad").fill(k.name);
  await page.getByLabel("E-posta").fill(k.email);
  await page.getByLabel("Parola", { exact: true }).fill(k.password);
  await page.getByLabel("KVKK aydınlatma metnini okudum").check();
  await page.getByRole("button", { name: "Hesap oluştur" }).click();

  await expect(page).toHaveURL(/\/panel/);

  await page.getByRole("button", { name: "Çıkış" }).click();
  await expect(page).toHaveURL(/\/$|\/giris/);

  // Çıkıştan sonra panel yine kapalı: oturum gerçekten sonlandı.
  await page.goto("/panel");
  await expect(page).toHaveURL(/\/giris/);

  await page.getByLabel("E-posta").fill(k.email);
  await page.getByLabel("Parola", { exact: true }).fill(k.password);
  await page.getByRole("button", { name: "Giriş yap" }).click();
  await expect(page).toHaveURL(/\/panel/);
});

test("yanlış parola anlaşılır hata verir ve panele sokmaz", async ({ page }) => {
  const k = testKullanicisi();
  await page.goto("/giris");
  await page.getByLabel("E-posta").fill(k.email);
  await page.getByLabel("Parola", { exact: true }).fill("yanlis-parola");
  await page.getByRole("button", { name: "Giriş yap" }).click();
  await expect(page.getByRole("alert")).toBeVisible();
  await expect(page).not.toHaveURL(/\/panel/);
});
```

- [ ] **Adım 2: Testi koş, başarısız olduğunu gör**

Çalıştır: `npx playwright test e2e/kimlik.spec.ts`
Beklenen: FAIL — `/giris` ve `/kayit` 404

- [ ] **Adım 3: better-auth'u kur**

```bash
npm install --workspace=@astro/site better-auth@1.7.6
```

`apps/site/src/lib/auth.ts` Drizzle bağdaştırıcısıyla kurulur; oturum çerezi
`httpOnly`, `sameSite: "lax"`, üretimde `secure`. E-posta doğrulaması açık ama
Görev 14'te Resend bağlanana kadar konsola yazan bir gönderici kullanılır —
geliştirmede sessizce başarısız olan bir e-posta, çalıştığını sanmaktan kötüdür.

- [ ] **Adım 4: Giriş ve kayıt sayfalarını yaz**

Form bileşenleri istemci bileşenidir; sayfa kabuğu sunucu bileşeni kalır ki
başlık ve açıklama SSR'da görünsün. Hata mesajı `role="alert"` taşır.
KVKK onay kutusu kayıt formunda zorunludur ve işaretlendiğinde `consents`
tablosuna metin sürümüyle yazılır.

`CikisDugmesi.tsx` `authClient.signOut()` çağırır ve `/`ye yönlendirir.

- [ ] **Adım 5: Testi koş, geçtiğini gör**

Çalıştır: `npx playwright test e2e/kimlik.spec.ts`
Beklenen: PASS (4 test)

- [ ] **Adım 6: Commit**

```bash
git add -A
git commit -m "feat(auth): kayıt, giriş ve çıkış

Oturum better-auth ile kendi Postgres'imizde: yönetici bir oturumu iptal
edebiliyor ve sağlayıcıya bağlı kalmıyoruz.

KVKK onayı kayıt anında metin sürümüyle birlikte kaydediliyor.

E-posta göndericisi şimdilik konsola yazıyor. Geliştirmede sessizce başarısız
olan bir e-posta, çalıştığını sanmaktan kötü."
```

---

## Görev 11: Panel kapısı — middleware, roller ve denetim kaydı

**Dosyalar:**
- Oluştur: `apps/site/src/middleware.ts`
- Oluştur: `apps/site/src/lib/yetki.ts`, `apps/site/src/lib/yetki.test.ts`
- Oluştur: `apps/site/src/lib/denetim.ts`
- Oluştur: `e2e/panel-kapisi.spec.ts`

**Arayüzler:**
- Üretir: `oturumGerekli()` → `{ user, session }`, oturum yoksa `/giris?devam=`e yönlendirir
- Üretir: `cihazYetkisiVar(userId, deviceId)` → `"operator" | "viewer" | null`
- Üretir: `denetimYaz({ actorUserId?, deviceId?, kind, payload, result, ip })`

- [ ] **Adım 1: Başarısız birim testini yaz**

`apps/site/src/lib/yetki.test.ts`:

```ts
import { describe, expect, it } from "vitest";

import { donusYolu, yoneticiMi, panelYoluMu } from "./yetki";

describe("panelYoluMu", () => {
  it("panel yollarını tanır", () => {
    expect(panelYoluMu("/panel")).toBe(true);
    expect(panelYoluMu("/panel/cihaz/abc")).toBe(true);
  });

  it("pazarlama sayfalarını korumaz", () => {
    expect(panelYoluMu("/platform")).toBe(false);
    expect(panelYoluMu("/")).toBe(false);
  });

  /* "/panelden" gibi bir yol panel değildir; önek karşılaştırması yanılırdı. */
  it("panel ile başlayan başka bir kelimeyi panel saymaz", () => {
    expect(panelYoluMu("/panelist")).toBe(false);
  });
});

describe("donusYolu", () => {
  it("girişten sonra istenen sayfaya döndürür", () => {
    expect(donusYolu("/panel/cihaz/42")).toBe("/giris?devam=%2Fpanel%2Fcihaz%2F42");
  });

  /*
   * Dış adrese dönüş kabul edilmez: ?devam=https://kotu.example ile açık
   * yönlendirme açığı olurdu.
   */
  it("dış adresi reddeder ve panele döner", () => {
    expect(donusYolu("https://kotu.example/")).toBe("/giris?devam=%2Fpanel");
  });

  it("protokolsüz çift eğik çizgiyi de reddeder", () => {
    expect(donusYolu("//kotu.example/")).toBe("/giris?devam=%2Fpanel");
  });
});

describe("yoneticiMi", () => {
  it("yalnızca admin rolünü kabul eder", () => {
    expect(yoneticiMi({ role: "admin" })).toBe(true);
    expect(yoneticiMi({ role: "operator" })).toBe(false);
    expect(yoneticiMi({ role: "customer" })).toBe(false);
  });
});
```

- [ ] **Adım 2: Testi koş, başarısız olduğunu gör**

Çalıştır: `npm test -- apps/site/src/lib/yetki`
Beklenen: FAIL — `Cannot find module './yetki'`

- [ ] **Adım 3: Uygula**

`panelYoluMu` tam segment karşılaştırması yapar (`yol === "/panel" ||
yol.startsWith("/panel/")`). `donusYolu` yalnızca tek eğik çizgiyle başlayan ve
ikinci karakteri eğik çizgi olmayan yolları kabul eder.

- [ ] **Adım 4: Testi koş, geçtiğini gör**

Çalıştır: `npm test -- apps/site/src/lib/yetki`
Beklenen: PASS (7 test)

- [ ] **Adım 5: middleware ve denetim kaydını bağla**

`middleware.ts` `matcher: ["/panel/:path*"]` ile yalnızca panel yollarında koşar.
Oturum çerezi yoksa `donusYolu` ile `/giris`e yönlendirir.

**Önemli:** middleware yalnızca çerezin *varlığına* bakar; oturumun geçerliliği
sayfanın kendi sunucu bileşeninde `oturumGerekli()` ile doğrulanır. Middleware'de
veritabanına gitmek her panel isteğine bir sorgu ekler ve süresi geçmiş bir
çerez yine de sayfada yakalanır.

`denetim.ts` yetki reddi, giriş, çıkış ve cihaz erişimini `auditEvents`e yazar.

- [ ] **Adım 6: e2e testini yaz ve koş**

`e2e/panel-kapisi.spec.ts`: anonim `/panel/cihaz/1` isteği `/giris?devam=...`e
gider; girişten sonra istenen sayfaya döner; `?devam=https://kotu.example` ile
gelen istek dış adrese gitmez.

Çalıştır: `npx playwright test e2e/panel-kapisi.spec.ts`
Beklenen: PASS

- [ ] **Adım 7: Commit**

```bash
git add -A
git commit -m "feat(panel): giriş kapısı, roller ve denetim kaydı

Middleware yalnızca çerezin varlığına bakıyor; oturumun geçerliliği sayfanın
sunucu bileşeninde doğrulanıyor. Middleware'de veritabanına gitmek her panel
isteğine bir sorgu ekliyordu ve süresi geçmiş çerez yine sayfada yakalanıyor.

?devam parametresi yalnızca tek eğik çizgiyle başlayan yolları kabul ediyor:
//kotu.example ve https://kotu.example açık yönlendirme açığıydı."
```

---

## Görev 12: Panel kabuğu ve cihaz listesi

**Dosyalar:**
- Oluştur: `apps/site/src/app/panel/layout.tsx`, `apps/site/src/app/panel/page.tsx`
- Oluştur: `apps/site/src/app/panel/hesap/page.tsx`
- Oluştur: `apps/site/src/components/PanelKenar.tsx`
- Oluştur: `apps/site/src/db/sorgular/cihaz.ts`
- Oluştur: `packages/ui/styles/panel.css`

**Arayüzler:**
- Tüketir: `oturumGerekli()`, `cihazYetkisiVar()`
- Üretir: `kullanicininCihazlari(userId)` → `Array<{ id, ad, serial, durum, lastSeenAt, yetki }>`

- [ ] **Adım 1: Başarısız testi yaz**

`e2e/panel-kabuk.spec.ts`: girişten sonra `/panel` kullanıcının adını ve "Henüz
cihaz eklenmedi" boş durumunu gösterir; kenar çubuğunda Cihazlar, Hesap ve Çıkış
bağlantıları vardır.

- [ ] **Adım 2: Testi koş, başarısız olduğunu gör**

Çalıştır: `npx playwright test e2e/panel-kabuk.spec.ts`
Beklenen: FAIL — `/panel` boş

- [ ] **Adım 3: Uygula**

Boş durum bilgi verir: cihaz nasıl eklenir, hangi fazda geleceği. Boş bir liste
göstermek kullanıcıya bir şeyin bozuk olduğunu düşündürür.

- [ ] **Adım 4: Testi koş, geçtiğini gör**

Çalıştır: `npx playwright test e2e/panel-kabuk.spec.ts`
Beklenen: PASS

- [ ] **Adım 5: Commit**

```bash
git add -A
git commit -m "feat(panel): panel kabuğu, cihaz listesi ve hesap sayfası

Boş durum cihazın nasıl eklendiğini anlatıyor. Boş bir liste göstermek
kullanıcıya bir şeyin bozuk olduğunu düşündürüyordu."
```

---

## Görev 13: Konsolun taşınması — genel demo ve giriş arkasındaki gerçek konsol

D7: tarayıcı içi senaryo `/platform/demo`da genel kalır (robota bağlanmaz),
gerçek konsol `/panel/cihaz/[id]`de giriş ve cihaz yetkisi arkasındadır.

**Dosyalar:**
- Oluştur: `apps/site/src/components/Konsol.tsx` (istemci bileşeni)
- Oluştur: `apps/site/src/app/platform/demo/page.tsx`
- Oluştur: `apps/site/src/app/panel/cihaz/[id]/page.tsx`
- Taşı: `client/src/console/telemetry.ts` → `apps/site/src/console/telemetry.ts`
  (Görev 8'de `client/` silinmeden önce bu taşıma yapılır; Görev 4'te taşınanlarla
  birlikte yapılabilir)
- Oluştur: `e2e/konsol.spec.ts`

**Arayüzler:**
- Tüketir: `connectTelemetry(cb)`, `createRobotScene`, `Telemetry`, `Command`
- Üretir: `<Konsol mod="demo" />` ve `<Konsol mod="canli" deviceId={id} />`

- [ ] **Adım 1: Başarısız testi yaz**

`e2e/konsol.spec.ts`:

```ts
import { expect, test } from "@playwright/test";

test("genel demo konsolu simülasyon olduğunu açıkça söyler", async ({ page }) => {
  await page.goto("/platform/demo");
  await expect(page.getByText(/SİMÜLASYON/i)).toBeVisible();
  // Demo robota bağlanmaz: acil durdurma düğmesi burada hiç bulunmaz.
  await expect(page.getByRole("button", { name: /ACİL DURDURMA/ })).toHaveCount(0);
});

test("anonim ziyaretçi gerçek konsolu göremez", async ({ page }) => {
  await page.goto("/panel/cihaz/1");
  await expect(page).toHaveURL(/\/giris/);
});

/*
 * Yetkisiz kullanıcıya 403 değil 404 verilir: 403, o kimlikte bir cihazın
 * gerçekten var olduğunu söyler ve cihaz kimliklerini tarayarak envanter
 * çıkarmaya izin verir.
 */
test("başkasının cihazına erişim 404 döner, 403 değil", async ({ page }) => {
  const k = {
    email: `yabanci-${Date.now()}@example.invalid`,
    password: "Gecici-Parola-123",
    name: "Yabancı Kullanıcı",
  };

  await page.goto("/kayit");
  await page.getByLabel("Ad soyad").fill(k.name);
  await page.getByLabel("E-posta").fill(k.email);
  await page.getByLabel("Parola", { exact: true }).fill(k.password);
  await page.getByLabel("KVKK aydınlatma metnini okudum").check();
  await page.getByRole("button", { name: "Hesap oluştur" }).click();
  await expect(page).toHaveURL(/\/panel/);

  // Kendisine hiçbir cihaz atanmadı: var olmayan da olsa her kimlik 404 olmalı.
  const yanit = await page.goto("/panel/cihaz/00000000-0000-0000-0000-000000000001");
  expect(yanit?.status()).toBe(404);
});
```

- [ ] **Adım 2: Testi koş, başarısız olduğunu gör**

Çalıştır: `npx playwright test e2e/konsol.spec.ts`
Beklenen: FAIL — `/platform/demo` 404

- [ ] **Adım 3: `Konsol.tsx`yi yaz**

Mevcut `pages/console.ts` içindeki okuma alanları, gösterge, pusula, kaydırıcı ve
düğmeler React'e çevrilir; sınıf adları `console.css` ile birebir korunur.
`mod="demo"` iken komut gönderme yolu hiç kurulmaz — düğmeleri devre dışı
bırakmak yetmez, genel bir sayfada komut yolunun var olmaması gerekir.

- [ ] **Adım 4: İki sayfayı bağla**

`/platform/demo` sunucu bileşeni; `Konsol` demo kipinde yüklenir.
`/panel/cihaz/[id]` önce `oturumGerekli()`, sonra `cihazYetkisiVar()` çağırır;
yetki yoksa `notFound()` — 403 cihazın var olduğunu ifşa eder.

- [ ] **Adım 5: Testi koş, geçtiğini gör**

Çalıştır: `npx playwright test e2e/konsol.spec.ts`
Beklenen: PASS

- [ ] **Adım 6: Commit**

```bash
git add -A
git commit -m "feat(konsol): genel demo ayrıldı, gerçek konsol giriş arkasına alındı

Demo kipinde komut yolu hiç kurulmuyor — genel bir sayfada düğmeleri devre dışı
bırakmak yetmez, yolun var olmaması gerekir.

Yetkisiz cihaz erişimi 404 dönüyor: 403 cihazın var olduğunu söylerdi."
```

---

## Görev 14: İletişim ve teklif formu, e-posta, KVKK onayı

**Dosyalar:**
- Oluştur: `apps/site/src/app/iletisim/page.tsx`, `IletisimFormu.tsx`
- Oluştur: `apps/site/src/app/iletisim/actions.ts` (sunucu eylemi)
- Oluştur: `apps/site/src/lib/eposta.ts`
- Oluştur: `apps/site/src/lib/iletisim-sema.ts`, `iletisim-sema.test.ts`
- Oluştur: `e2e/iletisim.spec.ts`

**Arayüzler:**
- Üretir: `iletisimSchema` (zod), `gonder(formData)` sunucu eylemi
- Üretir: `epostaGonder({ kime, konu, govde })`

- [ ] **Adım 1: Başarısız testi yaz**

`apps/site/src/lib/iletisim-sema.test.ts`:

```ts
import { describe, expect, it } from "vitest";

import { iletisimSchema } from "./iletisim-sema";

const gecerli = {
  tur: "iletisim" as const,
  ad: "Ada Lovelace",
  eposta: "ada@example.invalid",
  mesaj: "Platform hakkında bilgi almak istiyorum.",
  kvkkOnay: true,
};

describe("iletisimSchema", () => {
  it("geçerli formu kabul eder", () => {
    expect(iletisimSchema.parse(gecerli).ad).toBe("Ada Lovelace");
  });

  it("KVKK onayı olmadan reddeder", () => {
    expect(() => iletisimSchema.parse({ ...gecerli, kvkkOnay: false })).toThrow();
  });

  it("bozuk e-postayı reddeder", () => {
    expect(() => iletisimSchema.parse({ ...gecerli, eposta: "ada" })).toThrow();
  });

  it("çok kısa mesajı reddeder", () => {
    expect(() => iletisimSchema.parse({ ...gecerli, mesaj: "selam" })).toThrow();
  });

  /* Teklif talebinde şirket adı zorunlu: kurumsal satış görüşmesi onunla başlar. */
  it("teklif türünde şirket ister", () => {
    expect(() => iletisimSchema.parse({ ...gecerli, tur: "teklif" })).toThrow();
    expect(iletisimSchema.parse({ ...gecerli, tur: "teklif", sirket: "Barline" }).sirket).toBe("Barline");
  });

  it("baş ve sondaki boşlukları kırpar", () => {
    expect(iletisimSchema.parse({ ...gecerli, ad: "  Ada  " }).ad).toBe("Ada");
  });
});
```

- [ ] **Adım 2: Testi koş, başarısız olduğunu gör**

Çalıştır: `npm test -- apps/site/src/lib/iletisim`
Beklenen: FAIL — modül yok

- [ ] **Adım 3: Şemayı ve sunucu eylemini yaz**

Doğrulama sunucuda yapılır; istemci doğrulaması yalnızca kolaylıktır.
Kayıt `contactRequests` tablosuna, onay `consents` tablosuna metin sürümüyle
yazılır. E-posta gönderimi başarısız olursa **kayıt yine durur** ve kullanıcıya
başarı gösterilir: talep alınmıştır, e-posta yalnızca bildirimdir.

```bash
npm install --workspace=@astro/site resend@6.30.0
```

`eposta.ts` `RESEND_API_KEY` yoksa konsola yazar ve bunu açıkça söyler.

- [ ] **Adım 4: Testi koş, geçtiğini gör**

Çalıştır: `npm test -- apps/site/src/lib/iletisim`
Beklenen: PASS (6 test)

- [ ] **Adım 5: e2e testini yaz ve koş**

`e2e/iletisim.spec.ts`: JS kapalıyken form yine gönderilebilir (sunucu eylemi
ilerici geliştirmeyle çalışır); onay kutusu işaretlenmeden gönderim hata verir;
başarılı gönderimden sonra teşekkür mesajı görünür.

Çalıştır: `npx playwright test e2e/iletisim.spec.ts`
Beklenen: PASS

- [ ] **Adım 6: Commit**

```bash
git add -A
git commit -m "feat(iletisim): iletişim ve teklif formu, e-posta bildirimi

Doğrulama sunucuda; istemci doğrulaması yalnızca kolaylık. E-posta gönderimi
başarısız olsa bile talep kaydediliyor ve kullanıcıya başarı gösteriliyor:
talep alınmıştır, e-posta yalnızca bildirim.

Teklif türünde şirket adı zorunlu — kurumsal satış görüşmesi onunla başlıyor."
```

---

## Görev 15: Hukuki sayfalar (yer tutucu, açıkça işaretli)

**Dosyalar:**
- Oluştur: `apps/site/src/app/(hukuki)/layout.tsx`
- Oluştur: `apps/site/src/app/(hukuki)/{kvkk,gizlilik,cerez,kosullar,mesafeli-satis,iade}/page.tsx`
- Oluştur: `apps/site/src/data/hukuki.ts`
- Oluştur: `e2e/hukuki.spec.ts`

**Arayüzler:**
- Üretir: `HUKUKI_METINLER` — `Record<slug, { baslik, surum, govde, YER_TUTUCU }>`

- [ ] **Adım 1: Başarısız testi yaz**

`e2e/hukuki.spec.ts`:

```ts
import { expect, test } from "@playwright/test";

test.use({ javaScriptEnabled: false });

const sayfalar = ["/kvkk", "/gizlilik", "/cerez", "/kosullar", "/mesafeli-satis", "/iade"];

for (const yol of sayfalar) {
  test(`${yol} açılır ve yer tutucu olduğunu söyler`, async ({ page }) => {
    const yanit = await page.goto(yol);
    expect(yanit?.status()).toBe(200);
    // Hukukçu onayından geçmemiş bir metnin yayında olduğu gizlenmez.
    await expect(page.getByRole("alert")).toContainText("hukukçu onayından geçmemiştir");
  });

  test(`${yol} metin sürümünü gösterir`, async ({ page }) => {
    await page.goto(yol);
    // Onay kaydı bu sürüme referans verir; sürüm görünmezse onay ispatlanamaz.
    await expect(page.getByText(/Sürüm: /)).toBeVisible();
  });
}
```

- [ ] **Adım 2: Testi koş, başarısız olduğunu gör**

Çalıştır: `npx playwright test e2e/hukuki.spec.ts`
Beklenen: FAIL — altı yol 404

- [ ] **Adım 3: Uygula**

Metinler iskelet halinde, her biri sürüm numaralı. Sayfanın üstünde silinemez bir
`role="alert"` şeridi: "Bu metin yer tutucudur ve hukukçu onayından geçmemiştir."
`KURUM.YER_TUTUCU` doğru olduğu sürece bu şerit çizilir.

- [ ] **Adım 4: Testi koş, geçtiğini gör**

Çalıştır: `npx playwright test e2e/hukuki.spec.ts`
Beklenen: PASS (12 test)

- [ ] **Adım 5: Commit**

```bash
git add -A
git commit -m "feat(hukuki): altı hukuki sayfa, yer tutucu olduğu görünür şekilde

Her sayfa hukukçu onayından geçmediğini kendi üstünde söylüyor ve metin
sürümünü gösteriyor. Onay kayıtları bu sürüme referans veriyor; sürüm
görünmezse onay sonradan ispatlanamaz."
```

---

## Görev 16: Docker ile taşınabilirlik ve CI

D4'ün "sonra taşı" kısmının bedeli bugün ödenir: taşıma günü bunu sıfırdan
yazmak, build hattını yeniden kurmak demekti.

**Dosyalar:**
- Oluştur: `docker/site.Dockerfile`, `docker/gateway.Dockerfile`
- Değiştir: `docker/compose.yaml` (site + gateway servisleri, Caddy)
- Oluştur: `docker/Caddyfile`
- Oluştur: `.github/workflows/ci.yml`
- Oluştur: `.env.example` (tamamlanır)

- [ ] **Adım 1: CI iş akışını yaz**

```yaml
name: CI
on: [push, pull_request]

jobs:
  dogrula:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:16-alpine
        env:
          POSTGRES_USER: astro
          POSTGRES_PASSWORD: astro
          POSTGRES_DB: astro
        ports: ["5433:5432"]
        options: >-
          --health-cmd pg_isready --health-interval 5s --health-retries 10
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: "20.20.2"
          cache: npm
      - run: npm ci
      - run: npm run typecheck
      - run: npm test
      - run: npx playwright install --with-deps chromium
      - run: npm run e2e
        env:
          DATABASE_URL: postgres://astro:astro@localhost:5433/astro
          BETTER_AUTH_SECRET: ci-testleri-icin-sabit-sir-degeri
```

- [ ] **Adım 2: CI'ı yeşile getir**

Çalıştır: `npm run typecheck && npm test && npm run e2e`
Beklenen: üçü de yeşil. Yeşil değilse CI eklenmez — kırmızı bir CI, CI'sızlıktan
kötüdür çünkü kısa sürede görmezden gelinir.

- [ ] **Adım 3: Docker imajlarını yaz ve doğrula**

`site.Dockerfile` çok aşamalıdır ve `output: "standalone"` çıktısını kullanır.

```bash
docker build -f docker/site.Dockerfile -t astro-site .
docker compose -f docker/compose.yaml up -d
curl -sf http://localhost:8080/ | grep -q "<h1" && echo "site ayakta"
docker compose -f docker/compose.yaml down
```
Beklenen: `site ayakta`.

- [ ] **Adım 4: Commit**

```bash
git add -A
git commit -m "chore(ops): Docker imajları, compose yığını ve CI

Vercel'de koşarken Docker yolunu da çalışır tutuyoruz (D4): taşıma günü bunu
sıfırdan yazmak build hattını yeniden kurmak demekti. standalone çıktı
sayesinde imaj node_modules taşımıyor.

CI typecheck, birim testleri ve Playwright'ı koşuyor. Kırmızı bir CI
eklenmedi: kısa sürede görmezden gelinir ve CI'sızlıktan kötü olur."
```

---

## Görev 17: Faz 1+2 kapanışı — README, risk kaydı ve elle doğrulama

**Dosyalar:**
- Değiştir: `README.md`
- Değiştir: `docs/RISKLER.md`
- Oluştur: `docs/GELISTIRME.md`

- [ ] **Adım 1: Bütün doğrulamaları koş**

```bash
npm install
npm run typecheck
npm test
npm run build:site
npm run e2e
```
Her birinin çıktısı README'ye değil, bu görevin commit mesajına yazılır —
sayılar nereden geldiği belli olacak şekilde.

- [ ] **Adım 2: Tarayıcıda elle doğrula**

Şu altı şey ekranda görülmeden faz kapanmaz:
1. Ana sayfada açılış animasyonu oynar, model döner, kaydırdıkça altı özellik
   sırayla modelin üzerinde işaretlenir.
2. JavaScript kapatıldığında sayfa hâlâ okunur (bütün metin yerinde).
3. `/panel` anonim iken `/giris`e yönlenir.
4. Kayıt → panel → çıkış → panel kapalı döngüsü çalışır.
5. `/platform/demo` simülasyon rozetiyle çalışır, acil durdurma düğmesi yok.
6. Dar ekranda (375 px) gösteri modeli tanınmaz hale gelmez.

- [ ] **Adım 3: README ve risk kaydını güncelle**

`README.md` yeni yapıyı, çalıştırma komutlarını ve `docker compose` yolunu
anlatır. `docs/RISKLER.md`de R1–R4 açık kalır; hiçbiri bu fazda kapanmadı ve
kapanmış gibi yazılmaz.

- [ ] **Adım 4: Commit**

```bash
git add -A
git commit -m "docs: Faz 1+2 kapanışı — README ve doğrulama notları

Faz 0+1+2 tamamlandı. R1–R4 riskleri açık kalıyor: model, hukuki metinler,
kurum bilgileri ve fiyatlar hâlâ yer tutucu ve Faz 3'ün çıkış koşulları."
```

---

## Öz denetim notları

**Spec kapsamı:** §5 mimari → Görev 1, 2, 3, 16. §6 sayfa mimarisi ve SEO →
Görev 3–7, 15. §7 veri modeli → Görev 9 (Faz 2 tabloları; `products`, `orders`,
`payments`, `subscriptions`, `webhook_events` bilerek Faz 3'e bırakıldı).
§8 kimlik → Görev 10, 11, 12. §11 tasarım dili → Görev 4, 5, 6. §12 hata
yönetimi → Görev 2, 10, 14. §13 test stratejisi → her görev + Görev 16.

**Faz 3 ve 4'e bırakılanlar:** `PaymentProvider` arayüzü ve iyzico, abonelik,
e-ticaret, ağ geçidi robot köprüsü, WebRTC, OTA. Bu planda yok.

**Tip tutarlılığı:** `Telemetry`, `Command`, `ServerMessage` yalnızca
`@astro/protocol`ten gelir. `KURUM`, `PLANLAR`, `DESTEK_PAKETLERI`, `SAYFALAR`,
`HUKUKI_METINLER` tek tanım noktasına sahiptir. `oturumGerekli`,
`cihazYetkisiVar`, `denetimYaz`, `panelYoluMu`, `donusYolu`, `kurusBicimle`,
`sayfaMetadata` adları görevler arasında aynı yazımla kullanılır.
