#!/usr/bin/env bash
# ASTRO V1 — çalışma alanını doğru şekilde derler.
#
#   ./scripts/build.sh                      # tüm paketler
#   ./scripts/build.sh astro_audio          # yalnızca seçilen paket(ler)
#   ./scripts/build.sh --clean              # build/ install/ log/ silip baştan derle
#
# Neden düz `colcon build` değil:
#   1) Depo KÖKÜNDEN değil, ros2_ws/ içinden derlenmeli — aksi hâlde kökte ikinci bir
#      install/ ağacı oluşur ve `ros2 launch` hangisini bulursa onu çalıştırır.
#   2) venv'in Python'uyla çalıştırılmalı — setuptools, giriş noktalarının shebang'ini
#      kendisini çalıştıran yorumlayıcıdan üretir. Sistem colcon'u ile derlenirse
#      shebang /usr/bin/python3 olur ve düğümler edge-tts, faster-whisper, vosk,
#      sounddevice gibi venv paketlerini "kurulu değil" sanır.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WS="$ROOT/ros2_ws"
VPY="$ROOT/.venv/bin/python"
ROS_SETUP="/opt/ros/${ROS_DISTRO:-humble}/setup.bash"

CLEAN=0
PACKAGES=()
for arg in "$@"; do
  case "$arg" in
    --clean) CLEAN=1 ;;
    -h|--help) sed -n '2,8p' "${BASH_SOURCE[0]}" | sed 's/^# \?//'; exit 0 ;;
    *) PACKAGES+=("$arg") ;;
  esac
done

[ -f "$ROS_SETUP" ] || { echo "❌ ROS 2 bulunamadı: $ROS_SETUP" >&2; exit 1; }
[ -x "$VPY" ] || { echo "❌ venv yok: $VPY — önce ./scripts/install.sh çalıştırın" >&2; exit 1; }

if [ "$CLEAN" = "1" ]; then
  rm -rf "$WS/build" "$WS/install" "$WS/log"
  echo "🧹 build/ install/ log/ silindi"
fi

set +u                                  # ROS setup betikleri tanımsız değişken kullanır
# shellcheck disable=SC1090
source "$ROS_SETUP"
set -u

cd "$WS"
COLCON=("$VPY" -m colcon)
if ! "$VPY" -c "import colcon_core" >/dev/null 2>&1; then
  echo "⚠️  colcon venv'den import edilemiyor (python3-colcon-common-extensions kurulu mu?)."
  echo "    Sistem colcon'una düşülüyor — düğümler venv paketlerini göremeyebilir."
  COLCON=(colcon)
fi

if [ ${#PACKAGES[@]} -gt 0 ]; then
  "${COLCON[@]}" build --symlink-install --packages-select "${PACKAGES[@]}"
else
  "${COLCON[@]}" build --symlink-install
fi

cat <<EOF

✅ Derleme tamam. Kullanmak için:

   source $ROOT/.venv/bin/activate
   source $WS/install/setup.bash
   ros2 launch astro_audio audio.launch.py
EOF
