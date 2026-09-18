# ASTRO web

Üç sayfalık tanıtım sitesi ve kontrol konsolu.

```
web/
├── shared/      # telemetri sözleşmesi, sınırlar, senaryo sürücüsü (iki taraf da kullanır)
├── client/      # Vite + TypeScript + Three.js — üç sayfa
└── server/      # Fastify — statik servis + /ws telemetri (yalnızca yerel)
```

## Sayfalar

| Adres | İçerik |
|---|---|
| `/` | Tanıtım: 3B sahne, özellikler, çalışma sınırları |
| `/hakkimizda` | Kurumsal sayfa — şimdilik yalnızca başlık iskeleti |
| `/konsol` | Kontrol konsolu: canlı durum, kafa açısı, ses yönü, komut |

## Geliştirme

```bash
npm install
npm run dev                      # istemci, http://localhost:5173
npm run dev:server               # telemetri sunucusu, http://localhost:8420
```

İstemci tek başına da çalışır: sunucu bulunamazsa konsol, senaryoyu tarayıcıda
koşturur ve bunu `SİMÜLASYON` rozetiyle açıkça belirtir.

## Yerel ağda yayın

```bash
npm run build
npm start                        # Fastify, dist'i ve /ws'yi servis eder
```

## Vercel

Statik dağıtım. `vercel.json` hazır; Vercel projesinde **Root Directory = `web`**
seçilmelidir.

```bash
npx vercel            # önizleme dağıtımı
npx vercel --prod     # yayın
```

Vercel sunucusuz olduğu için kalıcı WebSocket kurulamaz: orada konsol her zaman
tarayıcı içi senaryoyla çalışır, gerçek robota bağlanmaz. Robota bağlanan sürüm
yerel ağdaki Fastify sunucusudur.

## Telemetri sözleşmesi

`shared/protocol.ts` tek anlaşmadır ve alanları gerçek ROS topic'lerinden
türetilmiştir. Faz 2'de yazılacak `astro_web` ROS köprüsü bu sözleşmeye uyar;
`server/src/index.ts` içinde değişecek tek satır `new MockSource()` yerine
`new BridgeSource()` olur.

## Giriş sahnesindeki model

`client/public/models/astro-hero.glb` **geçici bir yer tutucudur** — ASTRO'nun
kendisi değil, bir R2-D2 oyuncağının fotogrametri taramasıdır ve R2-D2 Lucasfilm
markasıdır. Kalıcı ve herkese açık bir tanıtım için değiştirilmelidir.

Model tek parça tarandığı için kubbe ayrı bir nesne değildir; `robot-model.ts`
üçgenleri ölçülmüş bir yükseklikte ikiye ayırır. Model değişirse dikiş yüksekliği
yeniden ölçülmelidir:

```bash
python3 scripts/measure-model-seam.py client/public/models/astro-hero.glb
python3 scripts/optimize-model.py <ham.glb> client/public/models/astro-hero.glb
```
