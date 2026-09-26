# Robot ↔ tarayıcı ağ geçidi.
#
# Vercel kalıcı WebSocket barındıramadığı için bu servis her zaman ayrı bir
# yerde koşar — bugün yerelde, ilerleyen fazda kendi sunucusunda.
#
# Çalışma katmanı node_modules taşımıyor: esbuild çıktısı bağımlılıkları içine
# gömüyor. Bağımlılıklar dışarıda bırakıldığında imaj 1,14 GB oluyordu, çünkü
# npm çalışma alanı ağacını tek bir paketin ihtiyacına göre budamıyor.

FROM node:20.20-alpine AS temel
WORKDIR /uygulama

# ── Bağımlılıklar ──
FROM temel AS bagimliliklar
COPY package.json package-lock.json ./
COPY apps/site/package.json apps/site/
COPY apps/gateway/package.json apps/gateway/
COPY packages/protocol/package.json packages/protocol/
COPY packages/ui/package.json packages/ui/
RUN npm ci

# ── Derleme ──
FROM temel AS derleme
# Çalışma alanı bağımlılıklarının hepsi köke yükselmiyor: npm bazılarını
# apps/*/node_modules altına koyuyor. Yalnızca kökteki node_modules
# kopyalandığında derleme "Module not found" ile düşüyordu.
COPY --from=bagimliliklar /uygulama ./
COPY . .
RUN npm run build --workspace=@astro/gateway

# ── Çalıştırma ──
FROM temel AS calisma
ENV NODE_ENV=production
RUN addgroup -g 1001 -S nodejs && adduser -S gateway -u 1001

COPY --from=derleme --chown=gateway:nodejs /uygulama/apps/gateway/dist ./dist

USER gateway
EXPOSE 8420
ENV PORT=8420 HOST=0.0.0.0
CMD ["node", "dist/index.js"]
