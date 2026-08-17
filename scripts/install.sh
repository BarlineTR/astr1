#!/usr/bin/env bash
# ASTRO V1 — tek komutluk kurulum
#
#   ./scripts/install.sh                # sistem paketleri + venv + derleme
#   ./scripts/install.sh --with-xtts    # ayrıca yerel XTTS ses klonlama (~5 GB)
#   ./scripts/install.sh --clean        # build/ install/ log/ silinip sıfırdan derlenir
#
# Betik yeniden çalıştırılabilir: var olanı bozmaz, eksiği tamamlar. .env dosyanız
# varsa asla üzerine yazılmaz.
set -euo pipefail

# ------------------------------------------------------------------ ayarlar
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WS="$ROOT/ros2_ws"
VENV="$ROOT/.venv"
VPY="$VENV/bin/python"
ROS_DISTRO_DEFAULT="humble"
ROS_SETUP="/opt/ros/${ROS_DISTRO:-$ROS_DISTRO_DEFAULT}/setup.bash"

WITH_XTTS=0
SKIP_APT=0
SKIP_BUILD=0
CLEAN=0

APT_PACKAGES=(
  # ROS sürücüleri — pip'te yok, apt'ten gelir
  "ros-humble-rplidar-ros"              # astro_lidar
  "ros-humble-depthai-ros"              # astro_vision (OAK-D Lite)
  "ros-humble-robot-state-publisher"    # astro_description (tf2)
  "python3-colcon-common-extensions"    # colcon build
  "python3-rosdep"
  # Yerel kütüphaneler — Python paketleri bunlara bağlanır
  "libportaudio2"                       # sounddevice (audio_capture_node)
  "espeak-ng"                           # pyttsx3 ve XTTS fonemleştirme
  "mpg123"                              # tts_node MP3 çalma (edge-tts/gTTS/ElevenLabs)
  "alsa-utils"                          # tts_node WAV çalma (XTTS)
  "git"
  "curl"
)

# ------------------------------------------------------------------ yardımcılar
step()  { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
ok()    { printf '   \033[1;32m✓\033[0m %s\n' "$*"; }
warn()  { printf '   \033[1;33m⚠  %s\033[0m\n' "$*"; WARNINGS+=("$*"); }
die()   { printf '\n\033[1;31m❌ %s\033[0m\n' "$*" >&2; exit 1; }
WARNINGS=()

usage() {
  sed -n '2,9p' "${BASH_SOURCE[0]}" | sed 's/^# \?//'
  cat <<'EOF'

Seçenekler:
  --with-xtts    Yerel XTTS ses klonlamayı da kur (scripts/install_xtts.sh)
  --skip-apt     apt adımını atla (sudo yoksa / paketler zaten kuruluysa)
  --skip-build   colcon build adımını atla
  --clean        build/ install/ log/ dizinlerini silip sıfırdan derle
  -h, --help     Bu yardımı göster
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    --with-xtts)  WITH_XTTS=1 ;;
    --skip-apt)   SKIP_APT=1 ;;
    --skip-build) SKIP_BUILD=1 ;;
    --clean)      CLEAN=1 ;;
    -h|--help)    usage; exit 0 ;;
    *)            die "Bilinmeyen seçenek: $1 (yardım için --help)" ;;
  esac
  shift
done

printf '\033[1m╔══════════════════════════════════════════╗\n'
printf '║   ASTRO V1 — Kurulum                     ║\n'
printf '╚══════════════════════════════════════════╝\033[0m\n'
echo "   Depo : $ROOT"

# ------------------------------------------------------------ 1. ön koşullar
step "1/7  Ön koşullar"

[ -f "$ROS_SETUP" ] || die "ROS 2 bulunamadı: $ROS_SETUP
   Ubuntu 22.04 + ROS 2 Humble gerekiyor: https://docs.ros.org/en/humble/Installation.html"
ok "ROS 2 $(basename "$(dirname "$ROS_SETUP")") — $ROS_SETUP"

command -v python3.10 >/dev/null 2>&1 || die "python3.10 bulunamadı (ROS Humble Python 3.10 ister)"
ok "python3.10 — $(python3.10 --version)"

if command -v nvidia-smi >/dev/null 2>&1; then
  ok "NVIDIA GPU — $(nvidia-smi --query-gpu=name --format=csv,noheader | head -1)"
else
  warn "NVIDIA GPU yok: STT/TTS CPU'da çalışır (.env içinde STT_FW_DEVICE=\"cpu\")"
fi

# ---------------------------------------------------------- 2. apt paketleri
step "2/7  Sistem paketleri (apt)"
if [ "$SKIP_APT" = "1" ]; then
  ok "atlandı (--skip-apt)"
else
  MISSING=()
  for p in "${APT_PACKAGES[@]}"; do
    dpkg -s "$p" >/dev/null 2>&1 || MISSING+=("$p")
  done

  if [ ${#MISSING[@]} -eq 0 ]; then
    ok "tüm paketler zaten kurulu (${#APT_PACKAGES[@]} paket)"
  elif [ "$(id -u)" != "0" ] && ! command -v sudo >/dev/null 2>&1; then
    warn "sudo yok — şunları elle kurun: sudo apt install ${MISSING[*]}"
  elif [ "$(id -u)" != "0" ] && ! sudo -n true 2>/dev/null && [ ! -t 0 ]; then
    # Etkileşimsiz kabukta sudo parola sorarsa betik takılır; sorup beklemek yerine bildir.
    warn "sudo parola ister ve terminal yok — elle kurun: sudo apt install ${MISSING[*]}"
  else
    echo "   Eksik: ${MISSING[*]}"
    SUDO=""; [ "$(id -u)" != "0" ] && SUDO="sudo"
    if $SUDO apt-get update -qq && $SUDO apt-get install -y "${MISSING[@]}"; then
      ok "${#MISSING[@]} paket kuruldu"
    else
      warn "apt kurulumu başarısız — elle kurun: ${MISSING[*]}"
    fi
  fi
fi

# ------------------------------------------------------------------- 3. uv
step "3/7  uv (Python paket yöneticisi)"
if ! command -v uv >/dev/null 2>&1; then
  echo "   uv kuruluyor..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi
command -v uv >/dev/null 2>&1 || die "uv kurulamadı. Elle: curl -LsSf https://astral.sh/uv/install.sh | sh"
ok "uv — $(uv --version)"

# ---------------------------------------------------- 4. Python sanal ortamı
step "4/7  Python sanal ortamı ve bağımlılıklar"
# --system-site-packages ZORUNLU: rclpy, sensor_msgs, std_msgs, launch, launch_ros ve
# ament_index_python PyPI'da yoktur, /opt/ros altından gelir. İzole bir venv hiçbir
# düğümü import edemez.
if [ -x "$VPY" ]; then
  ok "mevcut venv kullanılıyor: $VENV"
else
  uv venv --python 3.10 --system-site-packages "$VENV"
  ok "venv oluşturuldu: $VENV"
fi

VIRTUAL_ENV="$VENV" uv pip install -r "$ROOT/requirements.txt" --quiet
ok "requirements.txt kuruldu ($(VIRTUAL_ENV="$VENV" uv pip list 2>/dev/null | tail -n +3 | wc -l) paket)"

# ------------------------------------------------------------------ 5. .env
step "5/7  Yapılandırma (.env)"
if [ -f "$ROOT/.env" ]; then
  ok ".env zaten var — dokunulmadı"
else
  cp "$ROOT/.env.example" "$ROOT/.env"
  ok ".env, .env.example'dan oluşturuldu — API anahtarlarınızı doldurun"
fi

if [ ! -d "$ROOT/vosk-model-small-tr-0.3" ] && grep -q '^STT_ENGINE="vosk"' "$ROOT/.env" 2>/dev/null; then
  warn "STT_ENGINE=vosk seçili ama model dizini yok — bkz. README (Advanced STT Options)"
fi

# ------------------------------------------------------------------ 6. XTTS
step "6/7  XTTS (yerel ses klonlama)"
if [ "$WITH_XTTS" = "1" ]; then
  "$ROOT/scripts/install_xtts.sh"
  ok "XTTS kuruldu — .env içinde TTS_ENGINE=\"xtts\" yapın"
else
  ok "atlandı — istenirse: ./scripts/install.sh --with-xtts (veya ./scripts/install_xtts.sh)"
fi

# ------------------------------------------------------- 7. çalışma alanı derleme
step "7/7  ROS 2 çalışma alanı derleniyor"
if [ "$SKIP_BUILD" = "1" ]; then
  ok "atlandı (--skip-build)"
else
  if [ "$CLEAN" = "1" ]; then
    rm -rf "$WS/build" "$WS/install" "$WS/log"
    ok "build/ install/ log/ silindi"
  fi

  set +u                      # ROS setup betikleri tanımsız değişken kullanır
  # shellcheck disable=SC1090
  source "$ROS_SETUP"
  set -u

  cd "$WS"
  # colcon'u venv'in Python'uyla çalıştırmak KRİTİK: setuptools, giriş noktası
  # betiklerinin shebang'ini kendisini çalıştıran yorumlayıcıdan üretir. Sistem
  # colcon'u (/usr/bin/colcon) ile derlenirse shebang /usr/bin/python3 olur ve
  # `ros2 run` edge-tts, faster-whisper, sounddevice gibi venv paketlerini görmez.
  if "$VPY" -c "import colcon_core" >/dev/null 2>&1; then
    "$VPY" -m colcon build --symlink-install
    ok "derleme tamam (venv Python'u ile — giriş noktaları venv'i kullanır)"
  else
    warn "colcon venv'den import edilemedi; sistem colcon'u kullanılıyor.
        Düğümler venv paketlerini görmeyebilir; şununla çalıştırın:
        PYTHONPATH=\"$VENV/lib/python3.10/site-packages:\$PYTHONPATH\" ros2 launch ..."
    colcon build --symlink-install
  fi
  cd "$ROOT"
fi

# --------------------------------------------------------------- doğrulama
step "Doğrulama"
VERIFY_FAILED=0

if [ -f "$WS/install/setup.bash" ]; then
  set +u
  # shellcheck disable=SC1091
  source "$WS/install/setup.bash"
  set -u

  PKG_COUNT=$(ros2 pkg list 2>/dev/null | grep -c '^astro_' || true)
  if [ "$PKG_COUNT" -eq 7 ]; then
    ok "7 ROS paketi bulundu"
  else
    printf '   \033[1;31m✗\033[0m yalnızca %s/7 astro paketi bulundu\n' "$PKG_COUNT"
    VERIFY_FAILED=1
  fi

  # Her Python düğümü gerçekten import edilebiliyor mu?
  for m in astro_audio.audio_capture_node astro_audio.speech_recognition_node \
           astro_audio.tts_node astro_ai.ai_brain_node \
           astro_lidar.scan_filter_node astro_vision.face_detector_node; do
    if err=$("$VPY" -c "import $m" 2>&1); then
      ok "$m"
    else
      printf '   \033[1;31m✗\033[0m %s — %s\n' "$m" "$(echo "$err" | tail -1)"
      VERIFY_FAILED=1
    fi
  done

  # astro_base bir ament_cmake paketi: düğüm, modül değil betik olarak kurulur.
  if [ -x "$WS/install/astro_base/lib/astro_base/serial_bridge.py" ]; then
    ok "astro_base/serial_bridge.py"
  else
    printf '   \033[1;31m✗\033[0m astro_base/serial_bridge.py kurulmamış\n'
    VERIFY_FAILED=1
  fi

  # Giriş noktaları doğru yorumlayıcıya mı bakıyor?
  ENTRY="$WS/install/astro_audio/lib/astro_audio/tts_node"
  if [ -f "$ENTRY" ] && head -1 "$ENTRY" | grep -q "$VENV"; then
    ok "giriş noktaları venv Python'unu kullanıyor"
  elif [ -f "$ENTRY" ]; then
    warn "giriş noktası shebang'i venv'i göstermiyor ($(head -1 "$ENTRY")) — düğümler pip paketlerini göremeyebilir"
  fi
else
  warn "çalışma alanı derlenmemiş — doğrulama atlandı"
fi

# ------------------------------------------------------------------- özet
echo
if [ "$VERIFY_FAILED" = "1" ]; then
  printf '\033[1;31m❌ Kurulum tamamlandı ama doğrulama hatalı — yukarıdaki ✗ satırlarına bakın.\033[0m\n'
else
  printf '\033[1;32m✅ Kurulum tamam.\033[0m\n'
fi

if [ ${#WARNINGS[@]} -gt 0 ]; then
  printf '\n\033[1;33mUyarılar (%s):\033[0m\n' "${#WARNINGS[@]}"
  for w in "${WARNINGS[@]}"; do echo "   • $w"; done
fi

cat <<EOF

Kullanmaya başlamak için:

   source $VENV/bin/activate
   source $WS/install/setup.bash
   ros2 launch astro_bringup robot.launch.py

Yalnızca ses alt sistemi:

   ros2 launch astro_audio audio.launch.py

EOF

exit "$VERIFY_FAILED"
