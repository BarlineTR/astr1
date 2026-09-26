# ASTRO kurumsal web sitesi — tasarım belgesi

**Tarih:** 2026-09-26
**Dal:** `site/main` (ROS deposundan ayrılmış; kökte yalnızca site kodu)
**Durum:** onaylandı, uygulama planı bekliyor

---

## 1. Amaç

ASTRO'nun tanıtım sitesini, ticari bir robotik şirketinin kurumsal sitesine
dönüştürmek. Site altı işi yapacak:

1. Ürünü kurumsal alıcıya anlatmak (KUKA / Tesla / NVIDIA çizgisinde).
2. Arama motorlarında ve üretken arama araçlarında bulunmak.
3. Kullanıcı girişi ve rol ayrımı sağlamak.
4. Ödeme almak: destek paketi, abonelik, ürün satışı.
5. Dış ağdan robota erişim paneli sunmak.
6. İletişim ve teklif taleplerini toplamak.

## 2. Bugünkü durum (2026-09-26, çalıştırılarak ölçüldü)

| Ölçüm | Sonuç |
|---|---|
| Konum | `feat/web-tanitim-sitesi` dalında `web/`, 5 commit, 47 dosya. `origin/main`'de yok |
| Yığın | npm workspaces + Vite 5 (3 HTML girişi) + vanilla TS + three.js 0.170 + Fastify 5 |
| `npm test` | 16/16 geçiyor (vitest, 235 ms) |
| `npm run build` | Çalışıyor, 813 ms. three.js 520,77 KB / 132,20 KB gz |
| `npm run typecheck` | **Kırık:** kök `tsconfig.json` yok → `error TS5083` |
| `astro-hero.glb` | 2,7 MB |
| Üretilen HTML gövdesi | `<body><div id="app"></div></body>` — içerik yok |
| robots.txt, sitemap.xml, canonical, og:image, JSON-LD | Hiçbiri yok |
| Backend | Kullanıcı, oturum, veritabanı, e-posta, ödeme, denetim kaydı: yok |

### 2.1 Korunmaya değer olanlar

- **Görsel belirteç sistemi** (`client/src/styles/tokens.css`): siyah + pirinç, tek
  vurgu rengi üç işe ayrılmış, gradyan/parıltı yok. Kurumsal çizgiye zaten yakın.
- **Metnin koddan ayrılmış olması** (`client/src/data/content.ts`): bütün kopya tek
  modülde. Bu, sonradan İngilizce eklemenin bileşenlere dokunmadan yapılabilmesi
  demek — bilerek korunacak.
- **Telemetri sözleşmesi** (`shared/protocol.ts`): alanları gerçek ROS topic'lerinden
  türetilmiş, uydurma alan yok. Ağ geçidinin temeli bu.
- **16 birim testi**: taşıma sonrası hepsi geçmeye devam etmeli.

### 2.2 Atılacak olanlar

- **İstemcide çizilen sayfa gövdesi**: SEO hedefiyle bağdaşmaz.

### 2.3 Kabul edilmiş risk: giriş sahnesindeki model

`client/public/models/astro-hero.glb` bir R2-D2 oyuncağının fotogrametri taramasıdır
ve R2-D2 Lucasfilm markasıdır (`web/README.md` bunu zaten yazıyor). Gerçek ASTRO
taraması henüz yapılmadığı için model **geliştirme boyunca yerinde kalır** (D12).

Bu bilinçli bir risktir, gözden kaçmış bir şey değil: site herkese açık yayına
çıkmadan ve para almaya başlamadan önce model değiştirilmelidir. `docs/RISKLER.md`
dosyası bu maddeyi taşır ve Faz 3'ün (ödeme) çıkış koşuludur.

## 3. Doğrulanmış kısıtlar

### 3.1 Stripe Türkiye'ye merchant hesabı vermiyor
[stripe.com/global](https://stripe.com/global) desteklenen ülkeler listesinde Türkiye
yok. Yurt dışı kart tahsilatı üç yoldan biriyle olur: yabancı tüzel kişilik + Stripe,
merchant-of-record (Paddle / Lemon Squeezy), ya da hiç yapmamak. **Karar ertelendi**
→ ödeme katmanı sağlayıcıdan bağımsız bir arayüzün arkasına yazılacak.

### 3.2 Payoneer bir checkout değil
[Payoneer Checkout](https://www.payoneer.com/checkout/) mevcut ama
[resmî SSS'si](https://payoneer.custhelp.com/app/answers/detail/a_id/40689/~/payoneer-checkout---faq)
"şu anda Hong Kong tüzel kişiliğine sahip satıcılardan erken başvuru alıyoruz" diyor.
Türkiye'den erişilebilir bir kart altyapısı değil. Payoneer'in mimarideki yeri:
**yurt dışı kurumsal müşteriye kesilen faturanın tahsilat kanalı** — sitede bir "öde"
düğmesi değil, fatura üzerinde bir ödeme talimatı.

### 3.3 iyzico ve yasal yükümlülükler
iyzico tüzel kişilik + vergi levhası ister. Site para almaya başladığında zorunlu
olanlar: Mesafeli Satış Sözleşmesi, Teslimat ve İade Koşulları, Gizlilik Politikası,
KVKK Aydınlatma Metni, Çerez Politikası, Kullanım Koşulları, ETBİS kaydı.
**Bu metinler hukukçu onayından geçmeden yayına alınmaz**; kodda yer tutucu olarak
durur ve yer tutucu olduğu açıkça işaretlenir.

### 3.4 "Bağış" değil "destek paketi"
Türkiye'de yardım toplamak 2860 sayılı Yardım Toplama Kanunu'na tabidir ve izin
gerektirir. Aynı para akışı, **dijital destek paketi satışı** olarak kurgulandığında
olağan bir ürün satışıdır. Bahşiş özelliği bu şekilde tasarlanacak: alıcı bir tutar
seçer, karşılığında adı destekçi listesinde görünür ve isterse fatura alır.

### 3.5 Güvenlik: dış ağdan robot kontrolü
- Robot **dışa doğru** bağlanır (WSS). Müşteri ağında port yönlendirme yok.
- Web üzerinden acil durdurma bir **ek** katmandır, tek katman değildir. Firmware'deki
  500 ms watchdog (`arduino/astro_firmware/src/main.cpp`) yetkili kalır ve mimari onu
  bypass etmez.
- Gecikme ölçülür ve arayüzde gösterilir. Eşiği aşınca hareket komutları reddedilir —
  operatör 800 ms gecikmeyle kafayı yönlendirmeye çalışmaz.
- Her komut denetim kaydına yazılır: kim, hangi cihaz, ne zaman, hangi yük, sonuç.

### 3.6 KVKK
Panelde kamera görüntüsü veya yüz verisi göründüğü anda bu **özel nitelikli kişisel
veri**dir. Açık rıza akışı, saklama süresi ve veri envanteri Faz 4b'nin parçasıdır;
4b'den önce panelde görüntü akmaz.

## 4. Kararlar

| # | Karar | Gerekçe |
|---|---|---|
| D1 | Dal `site/main`, `git subtree split --prefix=web` ile | Beş web commit'inin geçmişi korunur; `--orphan` geçmişi atardı. Kökte ROS dosyası yok |
| D2 | Next.js 16 (bugün 16.3.6), App Router | SSR ile gerçek SEO, route handler'larla ödeme webhook'u, middleware ile oturum koruması, panel için aynı çatı |
| D3 | Tailwind **yok**, mevcut CSS belirteçleri korunur | Görsel dil zaten oturmuş; utility sınıflarına çevirmek bedava değil ve kazanç getirmiyor |
| D4 | Barındırma: Vercel + Neon, **taşınabilir yazılmış** | Faz 1–3'te sıfır sistem yönetimi. `output: "standalone"`, Docker dosyası ilk günden, sağlayıcıya özgü API kullanılmaz → tek VPS'e taşıma ucuz kalır |
| D5 | Ağ geçidi ayrı servis (Fastify, TS) | Vercel kalıcı WebSocket barındıramaz. Mevcut `server/` kodu buradan devam eder ve sözleşme tiplerini siteyle paylaşır |
| D6 | Robot ajanı Python, **ROS dalında** | Robot tarafı zaten Python/ROS. Site dalına ROS dosyası girmez. Sözleşme `packages/protocol`'den JSON Schema olarak dışa verilir, Python tarafı kendi testinde doğrular |
| D7 | Genel demo konsolu + giriş arkasında gerçek konsol | "Konsol giriş ekranından sonra çıksın" isteği gerçek konsol için karşılanır. Tarayıcı içi senaryo `/platform/demo`'da genel kalır: pazarlama değeri yüksek, robota bağlanmadığı için risk sıfır |
| D8 | `zod` sözleşmenin tek kaynağı | Ağ geçidi istemciden geleni doğrulamak zorunda; `z.infer` tipleri, `zod-to-json-schema` Python tarafını besler. Elle iki kopya tutulmaz |
| D9 | ORM: Drizzle | SQL'e yakın, Neon serverless ile de düz Postgres ile de aynı çalışır — D4'teki taşınabilirlik kararının devamı |
| D10 | Kimlik: better-auth 1.7.6 | Kendi Postgres'imizde oturum, rol ve oturum iptali; sağlayıcıya bağlı değil |
| D11 | İngilizce şimdilik yok, yolu kapanmıyor | Bütün kopya içerik modüllerinde durur; `[locale]` yönlendirmesi sonradan eklenir, bileşenler değişmez |
| D12 | **Mevcut `astro-hero.glb` kalır** (2026-09-26'da revize edildi) | Gerçek ASTRO taraması henüz yapılmadı; yer tutucu olmadan giriş sahnesi boşalır. Marka riski kabul edilmiş ve kayda geçmiştir (§2.3), yayına çıkmadan önce değiştirilmesi `docs/RISKLER.md`'de takip edilir. Sahne yükleme yolu tek dosyada kalır ki tarama gelince değişiklik tek satır olsun |

## 5. Mimari

```
site/main (kök — ROS dosyası yok)
├── apps/
│   ├── site/            Next.js 16 — pazarlama, SEO, oturum, ödeme, panel arayüzü
│   └── gateway/         Fastify — robot ↔ tarayıcı köprüsü (kalıcı WS)
├── packages/
│   ├── protocol/        zod sözleşmesi + JSON Schema üretimi
│   └── ui/              görsel belirteçler + paylaşılan bileşenler
├── docs/
└── docker/              tek VPS'e taşıma için (D4)
```

### 5.1 Bileşen sınırları

**`packages/protocol`** — Ne yapar: telemetri ve komut şemalarını tanımlar, JSON
Schema üretir, sürüm numarası taşır. Neye bağlı: yalnızca `zod`. Kimse onun içine
bakmadan kullanabilir.

**`apps/site`** — Ne yapar: bütün HTTP yüzeyi; sayfalar, oturum, ödeme, formlar,
denetim kaydının yazıldığı yer. Neye bağlı: Postgres, e-posta sağlayıcısı, ödeme
sağlayıcısı (arayüz üzerinden), `packages/protocol` (yalnızca panel arayüzü için).

**`apps/gateway`** — Ne yapar: robotun dışa doğru açtığı bağlantıyı tutar, tarayıcı
oturumunu doğrular, iki yönü birbirine bağlar, komutu hız sınırından geçirir, denetim
olayını siteye bildirir. Neye bağlı: `packages/protocol` ve sitenin açık anahtarı.
**Veritabanına sıcak yolda bakmaz** — yetki, sitenin imzaladığı kısa ömürlü jetonun
içindedir.

**Robot ajanı (ROS dalında)** — Ne yapar: ROS topic'lerini okur, sözleşmeye çevirir,
ağ geçidine WSS ile bağlanır, gelen komutu ROS'a yazar. Neye bağlı: ROS 2 ve
sözleşmenin JSON Schema'sı.

### 5.2 Veri akışı

```
Tarayıcı ──HTTPS──> apps/site ──> Postgres
    │                   │
    │                   └──> ödeme sağlayıcısı (webhook geri döner)
    │
    └──WSS + kısa ömürlü jeton──> apps/gateway <──WSS + cihaz jetonu── robot ajanı
                                       │                                    │
                                       └──denetim olayı──> apps/site    ROS 2 topic'leri
```

## 6. Sayfa mimarisi ve SEO

### 6.1 Sayfalar

| Adres | İş |
|---|---|
| `/` | Ürün anlatısı, ölçülmüş iddialar, birincil eylem |
| `/platform` | ASTRO V1: yetenekler, çalışma sınırları, teknik tablo |
| `/platform/demo` | Tarayıcı içi konsol demosu (robota bağlanmaz, açıkça işaretli) |
| `/cozumler/[sektor]` | Karşılama, bilgilendirme, eğitim — sektör başına bir sayfa |
| `/teknoloji` | Algı, sosyal bakış, güvenlik katmanları; ölçüm kaynaklarıyla |
| `/fiyatlandirma` | Planlar ve destek paketleri |
| `/hakkimizda` | Kurumsal anlatı (mevcut metin taşınır) |
| `/hakkimizda/yonetim` | Yönetim ekibi |
| `/basin` | Basın kiti: logo, görsel, künye, iletişim |
| `/iletisim` | Form + teklif (RFQ) talebi |
| `/destek` | Destek paketi satın alma |
| `/kaynaklar` | Teknik yazılar (SEO'nun asıl motoru) |
| `/giris`, `/kayit` | Kimlik |
| `/panel` | Cihaz listesi, hesap, abonelik, faturalar |
| `/panel/cihaz/[id]` | **Gerçek konsol** — giriş ve yetki arkasında |
| `/kvkk`, `/gizlilik`, `/cerez`, `/kosullar`, `/mesafeli-satis`, `/iade` | Hukuki |

### 6.2 SEO sözleşmesi

Faz 1'in kabul ölçütü, "meta etiket eklendi" değil şu: **ham HTML yanıtında sayfanın
`h1`'i ve gövde metni bulunur.** Bugünkü hatanın testi budur ve regresyon testi olarak
yazılır.

- Her sayfada `generateMetadata`: başlık, açıklama, canonical, OG, Twitter
- `sitemap.ts` ve `robots.ts` (Next.js dosya kuralları), otomatik üretilen
- JSON-LD: `Organization` (kök), `Product` (platform), `FAQPage` (platform ve
  fiyatlandırma), `BreadcrumbList`, `Article` (kaynaklar)
- 3B sahne `dynamic(..., { ssr: false })` ile yüklenir; LCP'yi statik bir poster
  görsel karşılar, sahne sonra devralır
- `prefers-reduced-motion` açıkken sahne hiç yüklenmez, poster kalır
- Üretken arama araçları için: her sayfada tek ve net bir özet paragrafı, tabloların
  gerçek `<table>` olarak işaretlenmesi, ölçüm değerlerinin metin içinde geçmesi

## 7. Veri modeli (Faz 2'de kurulur, sonraki fazlara hazır)

```
users              id, email, email_verified_at, password_hash, name, phone,
                   company, role, created_at, deleted_at
                   (deleted_at yalnızca hesabı devre dışı bırakır; KVKK silme
                    talebinde kayıt gerçekten silinir, denetim kaydında yalnızca
                    kimliksizleştirilmiş iz kalır)
sessions           better-auth yönetiminde
consents           id, user_id?, kind, text_version, ip, user_agent, created_at
                   (KVKK: kimin neyi hangi metin sürümünde onayladığı)
contact_requests   id, kind(iletisim|teklif), name, email, company, phone, message,
                   source_page, status, created_at
devices            id, serial, name, owner_user_id, token_hash, last_seen_at,
                   firmware_version, status, created_at, revoked_at
device_grants      id, device_id, user_id, role(operator|viewer), granted_by,
                   expires_at
audit_events       id, actor_user_id?, device_id?, kind, payload_json, result,
                   ip, created_at          (yalnızca ekleme; güncelleme/silme yok)
products           id, slug, kind(support|subscription|hardware), name, price_minor,
                   currency, vat_rate, active
orders             id, user_id?, email, status, total_minor, currency, provider,
                   provider_ref, invoice_no, created_at
order_items        id, order_id, product_id, qty, unit_price_minor, vat_rate
subscriptions      id, user_id, product_id, status, current_period_end,
                   provider, provider_ref, cancel_at
payments           id, order_id?, subscription_id?, provider, provider_ref,
                   status, amount_minor, currency, raw_json, created_at
webhook_events     id, provider, provider_event_id UNIQUE, received_at,
                   processed_at, raw_json      (idempotency buradan gelir)
```

Faz 2 yalnızca `users`, `sessions`, `consents`, `contact_requests`, `audit_events` ve
`devices`/`device_grants`'ın iskeletini kurar. Geri kalanı Faz 3 ve 4'te dolar; şema
baştan böyle tasarlandığı için sonradan eklemek göç yazmaktır, yeniden yazmak değil.

## 8. Kimlik ve yetki

Roller: `guest` → `customer` → `operator` → `admin`.

- Sayfa koruması `middleware.ts` ile; korunan her yol `/panel/*`
- Cihaz yetkisi rolden değil `device_grants`'tan gelir: bir operatör yalnızca
  kendisine verilmiş cihazı görür
- E-posta doğrulaması zorunlu; parola sıfırlama var
- Oturum iptali (kendi veritabanımızda olduğu için) yönetici tarafından mümkün
- Her yetki kararı `audit_events`'e yazılır

## 9. Ödeme katmanı

Tek arayüz, çok sağlayıcı:

```ts
interface PaymentProvider {
  readonly id: "iyzico" | "paddle" | "stripe";
  createCheckout(input: CheckoutInput): Promise<CheckoutResult>;
  verifyWebhook(req: RawRequest): Promise<WebhookEvent>;
  refund(paymentRef: string, amountMinor?: number): Promise<RefundResult>;
}
```

- İlk uygulama `iyzipay@2.0.70` (iyzico'nun resmî Node istemcisi), 3D Secure ile
- Tutarlar **her zaman** tam sayı kuruş (`price_minor`); kayan nokta kullanılmaz
- Webhook idempotent: `webhook_events.provider_event_id` tekil; aynı olay iki kez
  gelirse ikincisi hiçbir şey yapmaz
- Sipariş durumu webhook'la ilerler, tarayıcının döndüğü sayfayla değil — kullanıcı
  ödeme sonrası sekmeyi kapatırsa sipariş yine tamamlanır
- Sağlayıcı seçimi ortam değişkeniyle; kod hiçbir yerde `iyzipay`i doğrudan
  çağırmaz, yalnızca arayüzü çağırır (§3.1'de ertelenen kararın bedeli budur)

## 10. Uzaktan erişim ağ geçidi (Faz 4 tasarımı)

**Cihaz kaydı:** yönetici panelde cihaz oluşturur, tek kullanımlık eşleştirme kodu
üretilir. Robot ajanı kodu kullanıp uzun ömürlü cihaz jetonu alır; jetonun yalnızca
özeti (`token_hash`) veritabanında durur. İptal edilebilir.

**Robot bağlantısı:** ajan `wss://gw.../device` adresine bağlanır, jetonla kimliğini
verir, telemetriyi sözleşme çerçevelerinde akıtır. Dışa doğru bağlantı olduğu için
müşteri ağında port açılmaz.

**Tarayıcı bağlantısı:** site, kullanıcı `/panel/cihaz/[id]`'yi açtığında 60 saniye
ömürlü, Ed25519 ile imzalı bir jeton basar; içinde cihaz kimliği ve izinler vardır.
Ağ geçidi bunu açık anahtarla doğrular — sıcak yolda veritabanı sorgusu yok. Jetonun 60 saniyesi yalnızca **bağlantı kurulumu** içindir; kurulan bağlantı jeton dolduğunda kopmaz, ancak yetki iptal edildiğinde site ağ geçidine kapatma bildirimi gönderir.

**Komut yolu:** hız sınırı, izin kontrolü, sözleşme doğrulaması (`zod`), sonra robota.
Her komut denetim olayı olarak siteye bildirilir (kuyruk + yeniden deneme).

**Güvenlik sınırı:** ağ geçidi hareket sınırlarını *tekrar* zorlar ama tek zorlayan
değildir; asıl sınır firmware'de. Gecikme eşiği aşıldığında hareket komutları
reddedilir ve arayüzde neden reddedildiği yazılır.

**Sözleşme sürümlemesi:** `hello` çerçevesinde `v` alanı. Ajan ile ağ geçidi farklı
ana sürümdeyse bağlantı anlaşılır bir hatayla reddedilir — sessizce yanlış alan
okumaktan iyidir.

## 11. Tasarım dili

Referans çizgi (KUKA / Tesla / NVIDIA) şu üç şeyi ortak taşır: geniş görsel bloklar,
net ürün hiyerarşisi, ölçülebilir iddialar. Mevcut belirteç sistemi korunur; değişen
şey ölçek ve mimari:

- Bölüm ölçeği büyür: tam genişlik görsel bloklar, daha fazla beyaz alan
- Ürün hiyerarşisi görünür olur: platform → çözüm → teknoloji → fiyat
- İddialar ölçümle birlikte yazılır (±85°, 72°, 121°, 0,4–2,5 m) — bu zaten sitenin
  güçlü yanı ve kurumsal güven üretiyor, korunur
- Vurgu rengi (pirinç) üç işinde kalır: bölüm numarası, etkin durum, ölçülmüş değer
- Eklenen kurumsal öğeler: müşteri/ortak şeridi, sektör kartları, teknik veri tablosu,
  basın kiti, açık ve tek birincil eylem

## 12. Hata yönetimi

- **Form hataları** alan bazında, sunucu doğrulamasıyla; istemci doğrulaması yalnızca
  kolaylık
- **Ödeme hataları** kullanıcıya sağlayıcı diliyle değil anlaşılır Türkçe ile;
  ham hata `payments.raw_json`'a yazılır
- **Ağ geçidi kopması** panelde sessizce eski değer göstermez: bağlantı durumu ve son
  güncelleme zamanı her zaman görünür (mevcut `connected` alanı zaten bunu taşıyor)
- **Encoder susarsa** panel uyarır — `head.encoderOk` alanı arayüzde yutulmaz
  (sözleşme yorumunun açıkça istediği şey)
- **Beklenmeyen sunucu hatası** kullanıcıya izlenebilir bir hata kimliği gösterir

## 13. Test stratejisi

| Katman | Araç | Neyi korur |
|---|---|---|
| Birim | vitest | Mevcut 16 test geçmeye devam eder; sözleşme şemaları, fiyat/KDV hesabı, yetki kararları |
| SSR içerik | Playwright, `next build && next start` çıktısına karşı ham yanıtı okuyarak (JS çalıştırmadan) | **Ham HTML yanıtında `h1` ve gövde metni var** — bugünkü SEO hatasının regresyon testi |
| Sözleşme | vitest + JSON Schema | Üretilen şema ile TS tipleri uyumlu; ROS tarafı kendi deposunda aynı şemaya karşı test eder |
| Uçtan uca | Playwright | Giriş kapısı (`/panel` anonim erişimi reddeder), iletişim formu, iyzico sanal ödeme akışı |
| Webhook | vitest | Aynı olay iki kez gelince tek kayıt oluşur (idempotency) |
| CI | GitHub Actions | typecheck + lint + vitest + build + Playwright |

Kırık `npm run typecheck` Faz 0'da onarılır: kökte proje referanslı `tsconfig.json`.

## 14. Fazlama

| Faz | İçerik | Kabul ölçütü |
|---|---|---|
| **0** | Dal ayrımı, monorepo iskeleti, `typecheck` onarımı, CI | `site/main`'de ROS dosyası yok; typecheck, test, build üçü de yeşil |
| **1** | Next.js 16'ya taşıma, kurumsal sayfa mimarisi, SSR SEO, konsolun `/panel`e taşınması | Ham HTML'de `h1` ve gövde metni var; sitemap ve robots üretiliyor; 16 birim testi hâlâ geçiyor |
| **2** | better-auth + Postgres, roller, giriş/kayıt, iletişim + RFQ formu, e-posta, KVKK onay kaydı, denetim kaydı, panel iskeleti | `/panel` anonim erişimi reddediyor; gerçek konsol yalnızca girişten sonra görünüyor |
| **3a** | `PaymentProvider` + iyzico, destek paketi | Sanal ortamda uçtan uca ödeme; webhook idempotent |
| **3b** | Abonelik planları, panel erişiminin ödemeye bağlanması | Plan bitince erişim kapanıyor |
| **3c** | E-ticaret: sepet, e-fatura, kargo, iade | — |
| **4a** | Ağ geçidi, cihaz eşleştirme, telemetri + komut | Dış ağdan telemetri akıyor; her komut denetim kaydında |
| **4b** | WebRTC video + KVKK açık rıza | Rıza olmadan görüntü akmıyor |
| **4c** | Log ve teşhis indirme | — |
| **4d** | OTA: imzalı paket, rollback, ayrı güvenlik gözden geçirmesi | — |

**Bu turda uygulanacak: Faz 0 + 1 + 2.**

## 15. Bilinçli olarak kapsam dışı (YAGNI)

- İngilizce sürüm — yolu açık, şimdi yapılmıyor (D11)
- Blog yönetim arayüzü (CMS) — yazılar önce dosya olarak, MDX
- Çok kiracılı (multi-tenant) kurumsal hesap hiyerarşisi — tek kullanıcı, tek cihaz
  listesi yeter
- Mobil uygulama
- Canlı destek sohbeti
- Faz 3c ve 4b–4d bu turda kodlanmıyor; veri modeli ve arayüzler onları taşıyor

## 16. Açık sorular

**2026-09-26 tarihinde cevaplananlar:**

- **Kurum bilgileri** (§16.2): Faz 1–2 yer tutucu değerlerle yürür. Yer tutucular tek
  bir modülde (`apps/site/src/data/kurum.ts`) toplanır ve her biri açıkça
  `YER_TUTUCU` olarak işaretlenir; gerçek bilgi geldiğinde tek dosya değişir.
- **Gerçek ASTRO modeli** (§16.4): tarama yapılmadı, mevcut model kalır (D12, §2.3).
- **Fiyatlandırma** (§16.6): geliştirme aşaması için uydurma tutarlar kullanılır ve
  `GELISTIRME_FIYATI` olarak işaretlenir; gerçek fiyat gelmeden Faz 3 yayına çıkmaz.

**Hâlâ açık:**

1. **"CEO ve SEO'ya uyarlanabilsin"** ifadesini şöyle okudum: SEO = arama motoru
   görünürlüğü (Bölüm 6), CEO = kurumsal/yönetim sunumu, yani yönetim ekibi sayfası
   ve basın kiti (`/hakkimizda/yonetim`, `/basin`). Farklı bir şey kastedildiyse
   Bölüm 6.1 değişir.
2. **Kurum bilgilerinin gerçeği**: ticari unvan, vergi numarası, adres, telefon,
   ETBİS. Yer tutucuyla Faz 1–2 biter; hukuki sayfalar ve iyzico başvurusu bunlar
   gelmeden **tamamlanamaz** — Faz 3'ün giriş koşulu.
3. **Yönetim ekibi ve referanslar**: isim, görsel, unvan, müşteri listesi. Bugünkü
   `ABOUT` metni bilerek doğrulanamaz iddia içermiyor; kurumsal sayfa bunları ister.
4. **Alan adı ve e-posta**: SEO canonical, OG adresleri ve e-posta gönderimi için
   (SPF/DKIM) gerekli.

