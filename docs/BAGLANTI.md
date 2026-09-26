# Robot bağlantı portu

Robotun siteye bağlandığı yol. Üç parça var ve üçü de ayrı:

```
  robot ajanı                    ağ geçidi                     tarayıcı
  (ROS dalı, Python)      apps/gateway (Fastify)        apps/site konsolu
        │                            │                          │
        ├── POST /api/cihaz/eslestir ┼─────────> site ──────────┤
        │      kod → jeton           │                          │
        │                            │      POST /api/panel/jeton
        │                            │      (60 sn ömürlü jeton)│
        └── wss .../ws/cihaz ───────>│<────── wss .../ws/panel ─┘
```

**Robot dışa doğru bağlanır.** Müşteri ağında port açılmaz, yönlendirme
yapılmaz; bağlantıyı robot kurar ve ağ geçidi yalnızca kabul eder.

## Sözleşme

Bütün çerçeveler `packages/protocol/src/wire.ts` içinde zod ile tanımlı ve iki
tarafta da doğrulanıyor. Robot da istemci kadar şüpheli: jetonu ele geçirilmiş
bir ajan bozuk telemetri basabilir ve panel onu gerçek sanardı.

Makine okunur şema:

```ts
import { protocolJsonSchema } from "@astro/protocol/json-schema";
```

ROS tarafındaki Python ajanı kendi testinde bu şemaya karşı doğrular; sözleşme
iki depoda elle kopyalanmaz.

### Robot ajanı → ağ geçidi

| Çerçeve | Ne zaman |
|---|---|
| `cihaz.merhaba` | Bağlantının **ilk** çerçevesi. Jeton doğrulanana kadar başka çerçeve işlenmez |
| `cihaz.telemetri` | Telemetri (önerilen 10 Hz) |
| `cihaz.onay` | Komutun uygulanıp uygulanmadığı |
| `cihaz.pong` | Nabız yanıtı |

### Ağ geçidi → robot ajanı

| Çerçeve | Ne zaman |
|---|---|
| `gecit.kabul` | Jeton doğrulandı; sınırlar bildirilir |
| `gecit.komut` | Panelden gelen komut, `komutId` ile |
| `gecit.ping` | 5 saniyede bir |
| `gecit.hata` | Sözleşme, sürüm, jeton ya da yetki hatası |

### Tarayıcı ↔ ağ geçidi

Panel `panel.merhaba` ile başlar, `gecit.panel-kabul` alır; sonra
`gecit.cihaz-durum`, `gecit.telemetri` ve `gecit.onay` akar. Komutlar
`panel.komut` olarak gider.

## Eşleştirme

1. Panelden robot eklenir; **tek kullanımlık** eşleştirme kodu üretilir ve
   kullanıcıya **bir kez** gösterilir. Veritabanında yalnızca SHA-256 özeti
   durur — veritabanı sızsa bile kodlarla cihaz bağlanamaz.
2. Ajan `POST /api/cihaz/eslestir` ile kodu uzun ömürlü jetonla değiştirir.
   Kod o anda yakılır.
3. Ajan jetonla `…/ws/cihaz` adresine bağlanır.

Kod 24 saat geçerlidir. Kaybolursa geri getirilemez; cihaz sayfasından yenisi
üretilir ve bu **eski jetonu da iptal eder** — kod yenilemek "bu cihazı yeniden
bağla" demektir.

## Yetkilendirme

Ağ geçidi cihaz kayıtlarını tutmaz; bağlantı kurulurken **bir kez** siteye
sorar (`POST /api/gecit/dogrula`, `x-gecit-sirri` başlığıyla). Böylece iptal
edilen bir cihaz bir sonraki bağlantıda giremez ve ağ geçidi durumsuz kalır.
Site erişilemezse bağlantı kabul edilmez: "emin değilim" reddetmektir.

Panel jetonu 60 saniyeliktir ve tabloya yazılmaz; HMAC ile imzalanır. Kısa
ömürlü bir kayıt için tablo tutmak, temizlenmesi gereken bir çöp yığını demekti.
Kurulan bağlantı jeton dolunca kopmaz.

## Güvenlik sınırları

- **Hareket komutları** robot bağlı değilken ya da gecikme 800 ms'yi aştığında
  gönderilmez. O eşiğin üstünde operatör gördüğü şeyin geçmişine komut veriyor
  demektir.
- **Acil durdurma bu kısıttan muaftır.** Durdurmayı geciktirmek, geciken bir
  hareket komutundan çok daha kötü.
- **Ağ geçidi asıl güvenlik katmanı değildir.** Sınırları zorlayan katman
  firmware'dir; buradaki kontroller ikinci katman.
- Komutlar panel başına saniyede 20 ile sınırlı.
- Robot bağlı değilken komut **kuyruğa alınmaz**: sonradan teslim edilen bir
  hareket komutu, operatörün artık istemediği bir hareketi yaptırabilir.
- Her komut ağ geçidi günlüğüne kullanıcı ve cihaz kimliğiyle yazılır.

## Yerelde denemek

```bash
npm run db:up
npm run build:gateway
npm run dev:site          # ya da: bash scripts/yerel-sunucu.sh
bash scripts/gecit.sh     # ağ geçidi, 8420
```

Panelden robot ekleyip kodu alın, sonra referans ajanı çalıştırın:

```bash
node tools/sahte-robot.mjs --kod ABCD-EFGH-JKMN-PQRS --seri ASTRO-V1-000123
```

`tools/sahte-robot.mjs` **yalnızca testlik**: portun robot olmadan çalıştığını
göstermek ve sözleşmeyi örneklemek için. Gerçek ajan robot tarafında Python/ROS
olarak yazılacak ve ROS dalında duracak.
