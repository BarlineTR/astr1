#!/usr/bin/env bash
# baslat_hepsi.sh — Gateway + Site + Bridge

set -e
PROJE=~/Desktop/astr1
cd "$PROJE"

echo "=== [1] Eski prosesler durduruluyor ==="
pkill -f "astro_web_agent" 2>/dev/null || true
pkill -f "tsx.*index.ts"   2>/dev/null || true
pkill -f "next dev"        2>/dev/null || true
sleep 2

echo "=== [2] Ortam değişkenleri ==="
export GATEWAY_SHARED_SECRET=gelistirme-gecit-sirri-uretimde-degistirin
export DATABASE_URL=postgres://astro:astro@localhost:5432/astro
export BETTER_AUTH_SECRET=gelistirme-icin-sabit-deger-uretimde-degistirin
# PORT servis bazında atanıyor
export SITE_URL=http://localhost:3000
# Panelin tarayıcıdan gateway'e bağlanmak için kullandığı adres
export NEXT_PUBLIC_GECIT_URL=ws://192.168.1.111:8420
export NEXT_PUBLIC_SITE_URL=http://192.168.1.111:3000
export BETTER_AUTH_URL=http://localhost:3000

echo "=== [3] Gateway başlatılıyor (port 8420) ==="
PORT=8420 nohup npx --prefix "$PROJE/apps/gateway" tsx \
    "$PROJE/apps/gateway/src/index.ts" \
    > "$PROJE/gateway.log" 2>&1 &
GW_PID=$!
echo "Gateway PID: $GW_PID"
sleep 4
if nc -z localhost 8420 2>/dev/null; then
    echo "✅ Gateway hazır (port 8420)"
else
    echo "❌ Gateway başlamadı:"
    cat "$PROJE/gateway.log"
    exit 1
fi

echo "=== [4] Next.js site başlatılıyor (port 3000) ==="
cd "$PROJE/apps/site"
PORT=3000 nohup npm run dev \
    > "$PROJE/site.log" 2>&1 &
SITE_PID=$!
echo "Site PID: $SITE_PID"
cd "$PROJE"
sleep 12
if nc -z localhost 3000 2>/dev/null; then
    echo "✅ Site hazır (port 3000)"
else
    echo "❌ Site başlamadı:"
    tail -20 "$PROJE/site.log"
    exit 1
fi

echo "=== [5] Bridge başlatılıyor ==="
echo "Gateway  : ws://127.0.0.1:8420"
echo "Site     : http://192.168.1.111:3000"
echo ""
exec python3 "$PROJE/scripts/astro_web_agent.py" \
    --gateway ws://127.0.0.1:8420

