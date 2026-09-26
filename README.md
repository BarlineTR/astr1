# ASTRO — kurumsal web sitesi

ASTRO sosyal robot platformunun tanıtım sitesi, kullanıcı paneli ve robot ağ
geçidi. Bu dal **yalnızca** web sitesini içerir; ROS kodu `main` ve `feat/*`
dallarında durur.

```
apps/
├── site/        Next.js 16 — pazarlama, SEO, oturum, panel, eşleştirme API'si
└── gateway/     Fastify — robot ↔ tarayıcı köprüsü (kalıcı WebSocket)
packages/
├── protocol/    telemetri, komut ve tel sözleşmesi (zod) + JSON Schema üretimi
└── ui/          görsel belirteçler ve stiller
tools/           sahte-robot.mjs — portu robot olmadan denemek için referans ajan
docker/          imajlar ve yerel yığın
docs/            tasarım belgesi, uygulama planı, risk kaydı, bağlantı portu
```

## Çalıştırma

```bash
npm install
cp apps/site/.env.example apps/site/.env.local
npm run db:up                 # Postgres (Docker, 5433)
npm run db:migrate            # şemayı uygula
npm run dev:site              # http://localhost:3000
npm run build:gateway         # ağ geçidi paketlenir
bash scripts/gecit.sh         # http://localhost:8420
```

Ortam dosyası **`apps/site/.env.local`** içinde durur, kökte değil: Next ortam
dosyalarını uygulama dizininden okur.

## Doğrulama

```bash
npm run typecheck             # tsc -b + Next projesi
npm test                      # vitest — birim testleri
npm run e2e                   # Playwright — üretim çıktısına karşı
```

`npm run e2e` kendi sunucusunu ayağa kaldırır (`build` + `start`) ve
veritabanına ihtiyaç duyar.

## Sayfalar

| Adres | İçerik |
|---|---|
| `/` | Giriş sahnesi, kaydırma anlatısı, yetenekler |
| `/platform` | Ürün, ölçülmüş teknik veriler |
| `/platform/demo` | Konsol demosu — tarayıcı içi senaryo, robota bağlanmaz |
| `/cozumler`, `/cozumler/[sektor]` | Karşılama, bilgilendirme, eğitim |
| `/teknoloji` | Algı, sosyal bakış, güvenlik — ölçüm kaynaklarıyla |
| `/fiyatlandirma` | Planlar ve destek paketleri (geliştirme fiyatları) |
| `/hakkimizda`, `/hakkimizda/yonetim`, `/basin` | Kurumsal |
| `/iletisim` | İletişim ve teklif formu |
| `/giris`, `/kayit` | Kimlik |
| `/panel` | Cihazlar, hesap — **giriş arkasında** |
| `/panel/cihaz/ekle` | Robot ekleme ve eşleştirme kodu |
| `/panel/cihaz/[id]` | Gerçek kontrol konsolu, cihaz yönetimi — giriş + cihaz yetkisi arkasında |
| `/panel/abonelik`, `/panel/faturalar` | Plan ve ödeme (ödeme sağlayıcısı henüz bağlı değil) |
| `/kvkk`, `/gizlilik`, `/cerez`, `/kosullar`, `/mesafeli-satis`, `/iade` | Hukuki (taslak) |

## Bu kod tabanında bilinmesi gerekenler

- **İçerik sunucuda üretilir.** Ham HTML yanıtında `h1` ve gövde metni bulunmak
  zorunda; `e2e/ssr-icerik.spec.ts` bunu JavaScript **kapalıyken** ölçer.
  Taşımadan önceki hata tam olarak buydu ve JS açıkken hiç görünmüyordu.
- **Sözleşme iki girişli.** `@astro/protocol` sabitler ve tipler (çalışma zamanı
  bedeli yok), `@astro/protocol/schema` zod şemaları. Tarayıcı ikincisini almaz:
  tek giriş olduğunda zod her ziyaretçiye 28,5 KB (gz) olarak iniyordu.
- **Kopya içerik modüllerinde durur** (`apps/site/src/data/`). Bileşenin içine
  düz metin yazılmaz — İngilizce sürümün yolu böyle açık kalıyor.
- **CSS sınıf adları `showcase.ts` ile eşleşmek zorunda.** Kaydırma anlatısı
  çerçeveden bağımsız bir modül ve sınıf adlarıyla çalışıyor.
- **`.panel` konsol kartlarının**, `.pano` panel kabuğunun. İkisi aynı adı
  kullandığında kabuğun `display:flex` kuralı konsol ızgarasını bozuyor.
- **Ağ geçidi paketlenerek dağıtılır.** `tsc` göreli importları uzantısız
  bırakıyor ve Node ESM onları çözemiyor; ayrıca sözleşme paketi kaynak TS
  olarak yayımlanıyor. esbuild ikisini birlikte çözüyor.
- **Robot dışa doğru bağlanır.** Müşteri ağında port açılmaz. Ağ geçidi
  durumsuz bir röle; cihaz kayıtları sitenin veritabanında ve bağlantı
  kurulurken bir kez sorulur. Ayrıntı: `docs/BAGLANTI.md`.
- **Hareket komutları robot bağlı değilken ya da gecikme 800 ms'yi aştığında
  gönderilmez; acil durdurma bu kısıttan muaftır.** Durdurmayı geciktirmek,
  geciken bir hareket komutundan çok daha kötü.
- **Yer tutucular görünür.** Kurum bilgileri, fiyatlar ve hukuki metinler taslak
  ve sayfalar bunu kendileri söylüyor. Bkz. `docs/RISKLER.md`.

## Belgeler

- `docs/superpowers/specs/2026-09-26-kurumsal-web-sitesi-design.md` — tasarım ve kararlar
- `docs/superpowers/plans/2026-09-26-faz-0-1-2-kurumsal-site.md` — uygulama planı
- `docs/BAGLANTI.md` — robot bağlantı portu: sözleşme, eşleştirme, yetki, sınırlar
- `docs/RISKLER.md` — yayın öncesi kapatılması gereken maddeler

## Dağıtım

Vercel: `vercel.json` hazır, kök dizin bu dal. Ağ geçidi Vercel'de yaşayamaz
(kalıcı WebSocket) ve ayrı bir sunucuda koşar.

Tek VPS'e taşıma yolu da çalışır durumda tutulur:

```bash
docker compose -f docker/compose.yaml --profile tam up --build
```
