# ASTRO sitesi — tek VPS'e taşınabilirlik yolu (tasarım belgesi D4).
#
# Bugün Vercel'de koşuyor ama bu imaj da çalışır durumda tutuluyor: taşıma günü
# derleme hattını sıfırdan kurmak, bugün bir Dockerfile yazmaktan çok daha
# pahalı olurdu.

FROM node:20.20-alpine AS temel
WORKDIR /uygulama
ENV NEXT_TELEMETRY_DISABLED=1

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
# apps/site/node_modules altına koyuyor (better-auth böyle). Yalnızca kökteki
# node_modules kopyalandığında derleme "Module not found" ile düşüyordu.
COPY --from=bagimliliklar /uygulama ./
COPY . .
# standalone çıktı: imaj node_modules taşımaz, sunucu tek dosyadan koşar.
ENV BUILD_STANDALONE=1
RUN npm run build:site

# ── Çalıştırma ──
FROM temel AS calisma
ENV NODE_ENV=production
RUN addgroup -g 1001 -S nodejs && adduser -S nextjs -u 1001

COPY --from=derleme /uygulama/apps/site/public ./apps/site/public
COPY --from=derleme --chown=nextjs:nodejs /uygulama/apps/site/.next/standalone ./
COPY --from=derleme --chown=nextjs:nodejs /uygulama/apps/site/.next/static ./apps/site/.next/static

USER nextjs
EXPOSE 3000
ENV PORT=3000 HOSTNAME=0.0.0.0
CMD ["node", "apps/site/server.js"]
