#!/usr/bin/env bash
# Ağ geçidini yeniden başlatır (yerel geliştirme).
set -euo pipefail

KOK="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG="${LOG:-/tmp/claude-1000/gecit.log}"
PORT="${PORT:-8420}"

pkill -f "apps/gateway/dist/index.js" 2>/dev/null || true
for _ in $(seq 1 20); do
  ss -ltn "sport = :$PORT" 2>/dev/null | grep -q ":$PORT" || break
  sleep 0.3
done

cd "$KOK"
# Sır siteyle aynı olmalı; ikisi ayrışırsa doğrulama sessizce reddeder.
GATEWAY_SHARED_SECRET="$(grep '^GATEWAY_SHARED_SECRET=' apps/site/.env.local | cut -d= -f2-)" \
SITE_URL="http://localhost:3000" \
PORT="$PORT" \
nohup node apps/gateway/dist/index.js > "$LOG" 2>&1 &

for _ in $(seq 1 40); do
  if curl -sf -o /dev/null "http://localhost:$PORT/saglik"; then
    echo "ağ geçidi hazır: http://localhost:$PORT"
    exit 0
  fi
  sleep 0.5
done

echo "ağ geçidi açılmadı, log:" >&2
tail -20 "$LOG" >&2
exit 1
