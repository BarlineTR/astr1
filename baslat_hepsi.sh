#!/usr/bin/env bash
# ========================================================
#   ASTRO V1 — Tam Sistem Başlatıcı
#   Bileşenler:
#     1) Gateway (Fastify WebSocket :8420)
#     2) Web Site & Kontrol Paneli (Next.js :3000)
#     3) Robot Web Köprüsü (astro_web_agent.py)
#     4) Fiziksel Robot & GPT-4o Ses/Algı (ROS 2 Humble, USE_4O=true)
# ========================================================

set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

echo "========================================================"
echo "  🚀 ASTRO V1 — Tam Sistem Başlatılıyor (USE_4O=true)"
echo "========================================================"

# --- 1. Eski Prosesleri Temizle ---
echo "[1/4] Eski düğümler ve arka plan servisleri temizleniyor..."
pkill -f "astro_web_agent"        2>/dev/null || true
pkill -f "tsx.*index.ts"          2>/dev/null || true
pkill -f "next dev"               2>/dev/null || true
pkill -f "astro_social_gaze"      2>/dev/null || true
pkill -f "serial_bridge"          2>/dev/null || true
pkill -f "standalone_gaze"        2>/dev/null || true
pkill -f "consciousness"          2>/dev/null || true
pkill -f "astro_realtime"         2>/dev/null || true
pkill -f "audio_stream"           2>/dev/null || true
pkill -f "scan_filter"            2>/dev/null || true
sleep 2

# --- 2. Ortam Değişkenleri & ROS2 Kaynakları ---
echo "[2/4] Ortam değişkenleri ve ROS 2 kütüphaneleri yükleniyor..."
export GATEWAY_SHARED_SECRET=gelistirme-gecit-sirri-uretimde-degistirin
export DATABASE_URL=postgres://astro:astro@localhost:5432/astro
export BETTER_AUTH_SECRET=gelistirme-icin-sabit-deger-uretimde-degistirin
export BETTER_AUTH_URL=http://localhost:3000
export NEXT_PUBLIC_GECIT_URL=ws://192.168.1.111:8420
export NEXT_PUBLIC_SITE_URL=http://192.168.1.111:3000
export NEXT_TELEMETRY_DISABLED=1
export PORT=8420
export USE_4O=true
export HOME=/home/okistech

# Standalone modülleri ve Python paket yolları
export PYTHONPATH="$DIR/standalone:/home/okistech/.local/lib/python3.10/site-packages:${PYTHONPATH:-}"

if [ -f "/opt/ros/humble/setup.bash" ]; then
    source /opt/ros/humble/setup.bash
fi

if [ -f "$DIR/.venv/bin/activate" ]; then
    source "$DIR/.venv/bin/activate"
fi

if [ -f "$DIR/ros2_ws/install/setup.bash" ]; then
    source "$DIR/ros2_ws/install/setup.bash"
fi

# Temiz çıkış kapanış kapanı (Ctrl+C basıldığında tüm arka planı kapat)
GW_PID=""
SITE_PID=""
BRIDGE_PID=""

cleanup() {
    echo ""
    echo "========================================================"
    echo "  🛑 ASTRO V1 Sistemi Kapatılıyor..."
    echo "========================================================"
    [ -n "$BRIDGE_PID" ] && kill "$BRIDGE_PID" 2>/dev/null || true
    [ -n "$SITE_PID" ] && kill "$SITE_PID" 2>/dev/null || true
    [ -n "$GW_PID" ] && kill "$GW_PID" 2>/dev/null || true
    pkill -f "astro_web_agent"   2>/dev/null || true
    pkill -f "tsx.*index.ts"     2>/dev/null || true
    pkill -f "next dev"          2>/dev/null || true
    pkill -f "serial_bridge"     2>/dev/null || true
    pkill -f "astro_realtime"    2>/dev/null || true
    pkill -f "audio_stream"      2>/dev/null || true
    echo "✅ Tüm servisler güvenle durduruldu."
}
trap cleanup EXIT INT TERM

# --- 3. Web & Ağ Geçidi Servisleri ---
echo "[3/4] Web altyapısı başlatılıyor..."

# 3a. Gateway
echo "  [+] Gateway başlatılıyor (:8420)..."
nohup npx --prefix "$DIR/apps/gateway" tsx \
    "$DIR/apps/gateway/src/index.ts" \
    > "$DIR/gateway.log" 2>&1 &
GW_PID=$!
sleep 4
if nc -z localhost 8420 2>/dev/null; then
    echo "      ✅ Gateway hazır (port 8420)"
else
    echo "      ❌ Gateway başlamadı:"
    cat "$DIR/gateway.log" | tail -10
    exit 1
fi

# 3b. Next.js Site
echo "  [+] Next.js Web Paneli başlatılıyor (:3000)..."
cd "$DIR/apps/site"
nohup npx next dev -H 0.0.0.0 -p 3000 \
    > "$DIR/site.log" 2>&1 &
SITE_PID=$!
cd "$DIR"
sleep 10
if nc -z localhost 3000 2>/dev/null; then
    echo "      ✅ Panel hazır (http://192.168.1.111:3000)"
else
    echo "      ⏳ Panel arka planda derlenmeye devam ediyor..."
fi

# 3c. Robot Web Köprüsü
echo "  [+] Robot Web Köprüsü bağlanıyor..."
nohup python3 -u "$DIR/scripts/astro_web_agent.py" \
    --gateway ws://127.0.0.1:8420 \
    > "$DIR/bridge.log" 2>&1 &
BRIDGE_PID=$!
sleep 3
if grep -q "kabul etti" "$DIR/bridge.log" 2>/dev/null; then
    echo "      ✅ Köprü Gateway'e bağlandı (Telemetri AKTİF)"
else
    echo "      ℹ️ Köprü başlatıldı (log: $DIR/bridge.log)"
fi

echo ""
echo "========================================================"
echo "  🌐 Kontrol Paneli : http://192.168.1.111:3000"
echo "  ⚡ Ağ Geçidi      : ws://192.168.1.111:8420"
echo "========================================================"
echo ""

# --- 4. ROS 2 Robot & GPT-4o Düğümleri (Ön Plan) ---
echo "[4/4] 🤖 ROS 2 Düğümleri Başlatılıyor (USE_4O=true)..."
echo "      (Sistemi durdurmak için: Ctrl+C)"
echo "--------------------------------------------------------"

ros2 launch astro_bringup astro_social_gaze.launch.py "$@"
