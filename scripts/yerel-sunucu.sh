#!/usr/bin/env bash
# Üretim sunucusunu temiz şekilde yeniden başlatır.
#
# Elle `pkill` + `nohup` ikilisi yarışa giriyordu: pkill yeni süreci de
# öldürüyor ya da eski süreç portu bırakmadan yenisi bağlanmaya çalışıyordu.
set -euo pipefail

KOK="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG="${LOG:-/tmp/claude-1000/site.log}"
PORT="${PORT:-3000}"

pkill -f "next-server" 2>/dev/null || true
pkill -f "next start" 2>/dev/null || true

for _ in $(seq 1 20); do
  ss -ltn "sport = :$PORT" 2>/dev/null | grep -q ":$PORT" || break
  sleep 0.3
done

cd "$KOK"
nohup npm run start:site > "$LOG" 2>&1 &

for _ in $(seq 1 40); do
  if curl -sf -o /dev/null "http://localhost:$PORT/"; then
    echo "sunucu hazır: http://localhost:$PORT"
    exit 0
  fi
  sleep 0.5
done

echo "sunucu açılmadı, log:" >&2
tail -20 "$LOG" >&2
exit 1
