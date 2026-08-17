#!/usr/bin/env bash
# ASTRO V1 — Coqui XTTS v2 (yerel ses klonlama) kurulumu
#
# XTTS'i PyPI'dan DEĞİL, doğrudan GitHub deposundan (fork) kurar. Coqui TTS 0.22.0
# bakımda olmadığı için `pip install TTS` bugünkü paket sürümleriyle import edilebilen
# ama çalışmayan bir ortam üretiyor; bu betik denenmiş sürüm kümesini sabitler.
#
# ÖNEMLİ: XTTS ASTRO'nun kendi .venv'ine kurulamaz. XTTS numpy 1.26.4 ister
# (derlenmiş monotonic_align cython uzantısı numpy 1.x ABI'sine göre), ASTRO ise
# rclpy ABI uyumu için numpy 2.2.6'ya sabitlenmiştir. Bu yüzden XTTS kendi
# venv'inde yaşar ve tts_node onunla ayrı bir süreç (xtts_worker.py) üzerinden konuşur.
#
# Kullanım:
#   ./scripts/install_xtts.sh
#
# Ortam değişkenleriyle:
#   TTS_XTTS_HOME=/başka/yol ./scripts/install_xtts.sh   # kurulum dizini
#   XTTS_SKIP_DOWNLOAD=1 ./scripts/install_xtts.sh       # modeli önceden indirme
set -euo pipefail

REPO_URL="${TTS_XTTS_REPO:-https://github.com/yunusemretom/TTS.git}"
XTTS_HOME="${TTS_XTTS_HOME:-$HOME/.astro/tts}"
PY_VERSION="3.10"   # setup.py Python 3.9–3.11 ister; 3.12+ reddedilir

# Aşağıda XTTS_HOME'a cd'leniyor; ASTRO deposunun kökünü şimdi çözelim.
ASTRO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

say()  { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m⚠️  %s\033[0m\n' "$*"; }
die()  { printf '\033[1;31m❌ %s\033[0m\n' "$*" >&2; exit 1; }

# ---------------------------------------------------------------- ön koşullar
command -v git >/dev/null 2>&1 || die "git bulunamadı: sudo apt install git"

if ! command -v uv >/dev/null 2>&1; then
  die "uv bulunamadı. Kurmak için:
     curl -LsSf https://astral.sh/uv/install.sh | sh
     ve yeni bir kabuk açın (veya: source \$HOME/.local/bin/env)"
fi

if ! command -v espeak-ng >/dev/null 2>&1; then
  warn "espeak-ng yok — fonemleştirme çalışmaz. Kurun: sudo apt install espeak-ng"
fi

# ------------------------------------------------------------ depoyu getir/güncelle
if [ -d "$XTTS_HOME/.git" ]; then
  say "Mevcut depo güncelleniyor: $XTTS_HOME"
  git -C "$XTTS_HOME" fetch --depth 1 origin || warn "fetch başarısız, mevcut kopya kullanılıyor"
  git -C "$XTTS_HOME" reset --hard origin/HEAD 2>/dev/null \
    || git -C "$XTTS_HOME" pull --ff-only \
    || warn "güncelleme başarısız, mevcut kopya kullanılıyor"
elif [ -e "$XTTS_HOME" ]; then
  die "$XTTS_HOME var ama git deposu değil. Silin veya TTS_XTTS_HOME ile başka yol verin."
else
  say "Depo klonlanıyor: $REPO_URL -> $XTTS_HOME"
  mkdir -p "$(dirname "$XTTS_HOME")"
  git clone --depth 1 "$REPO_URL" "$XTTS_HOME"
fi

cd "$XTTS_HOME"
VENV="$XTTS_HOME/.venv"
VPY="$VENV/bin/python"

# ------------------------------------------------------------------- venv + paket
if [ -x "$VPY" ]; then
  say "Mevcut sanal ortam kullanılıyor: $VENV (sıfırlamak için silin)"
else
  say "Python $PY_VERSION sanal ortamı hazırlanıyor: $VENV"
  uv venv --python "$PY_VERSION" "$VENV"
fi

say "TTS deposu düzenlenebilir kipte kuruluyor (pip'ten değil, bu klondan)"
VIRTUAL_ENV="$VENV" uv pip install -e .

# ------------------------------------------------------ 1a. sürücüye uygun torch
# Varsayılan çözümleme sürücünüzden yeni bir CUDA derlemesi kurabilir; o durumda
# torch.cuda.is_available() sessizce False döner ve her şey CPU'da çalışır.
CUDA_TAG=""
if command -v nvidia-smi >/dev/null 2>&1; then
  DRIVER_CUDA="$(nvidia-smi 2>/dev/null | sed -n 's/.*CUDA Version: *\([0-9]\+\.[0-9]\+\).*/\1/p' | head -1)"
  if [ -n "$DRIVER_CUDA" ]; then
    CUDA_MAJOR="${DRIVER_CUDA%%.*}"
    CUDA_MINOR="${DRIVER_CUDA##*.}"
    if [ "$CUDA_MAJOR" -gt 12 ] || { [ "$CUDA_MAJOR" -eq 12 ] && [ "$CUDA_MINOR" -ge 4 ]; }; then
      CUDA_TAG="cu124"
    elif [ "$CUDA_MAJOR" -eq 12 ]; then
      CUDA_TAG="cu121"
    else
      CUDA_TAG="cu118"
    fi
    say "GPU algılandı (sürücü CUDA $DRIVER_CUDA) -> torch $CUDA_TAG derlemesi"
  fi
fi

if [ -n "$CUDA_TAG" ]; then
  # --index-url (extra olmayan) KULLANMAYIN: nvidia-* bağımlılıkları çözülemez.
  VIRTUAL_ENV="$VENV" uv pip install \
    "torch==2.5.1+$CUDA_TAG" "torchaudio==2.5.1+$CUDA_TAG" \
    --extra-index-url "https://download.pytorch.org/whl/$CUDA_TAG" \
    --index-strategy unsafe-best-match
else
  warn "NVIDIA GPU bulunamadı — CPU derlemesi kuruluyor (XTTS CPU'da çok yavaştır)"
  VIRTUAL_ENV="$VENV" uv pip install "torch==2.5.1" "torchaudio==2.5.1" \
    --extra-index-url https://download.pytorch.org/whl/cpu \
    --index-strategy unsafe-best-match
fi

# ------------------------------------------------------- 1b. çalışan paket sürümleri
# librosa 0.10.0  -> pkg_resources import ediyor, setuptools 81+ bunu kaldırdı
# transformers 5.x -> SampleOutput / LogitsWarper kaldırıldı, stream_generator patlıyor
# numpy 2.x        -> derlenmiş monotonic_align uzantısı numpy 1.x ABI'sine göre
say "Bilinen çalışan paket sürümleri sabitleniyor"
VIRTUAL_ENV="$VENV" uv pip install \
  "librosa==0.10.2.post1" "transformers==4.40.2" "numpy==1.26.4" "scipy==1.11.4"

# ------------------------------------------------------------- 1c. espeak ve nltk
if command -v espeak-ng >/dev/null 2>&1; then
  # Fonemleştirici "espeak" adında bir çalıştırılabilir arar; sudo'ya gerek yok.
  ln -sf "$(command -v espeak-ng)" "$VENV/bin/espeak"
  say "espeak symlink'i oluşturuldu: $VENV/bin/espeak"
fi

say "nltk verisi indiriliyor"
env PYTHONPATH= "$VPY" -c \
  "import nltk; [nltk.download(p, quiet=True) for p in ['averaged_perceptron_tagger','averaged_perceptron_tagger_eng','punkt','cmudict']]" \
  || warn "nltk verisi indirilemedi (yalnızca bazı diller etkilenir)"

# ------------------------------------------------------------------- doğrulama
say "Kurulum doğrulanıyor"
env PYTHONPATH= "$VPY" -c "
import torch, TTS
from TTS.api import TTS as _T
print('torch', torch.__version__, '| cuda', torch.cuda.is_available())
print('gpu  ', torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'YOK - CPU modunda')
"

# --------------------------------------------------------- modeli önceden indir
if [ "${XTTS_SKIP_DOWNLOAD:-0}" != "1" ]; then
  say "XTTS v2 modeli indiriliyor (~1.8 GB, ~/.local/share/tts altına, bir kez)"
  # COQUI_TOS_AGREED=1 lisans onayı sorusunu atlar (etkileşimsiz çalıştırmada gerekir).
  env PYTHONPATH= COQUI_TOS_AGREED=1 "$VPY" -c "
from TTS.utils.manage import ModelManager
ModelManager().download_model('tts_models/multilingual/multi-dataset/xtts_v2')
print('model hazır')
" || warn "Model indirilemedi — ilk konuşmada otomatik indirilecek"
fi

cat <<EOF

✅ XTTS kurulumu tamam.
   Depo : $XTTS_HOME
   Venv : $VENV

Kullanmak için .env dosyanızda:

   TTS_ENGINE="xtts"
   TTS_XTTS_HOME="$XTTS_HOME"
   # TTS_XTTS_SPEAKER_WAV="/tam/yol/kendi_sesiniz.wav"   # boşsa paketteki voices/astro.wav

Sonra derleyip başlatın:

   cd $ASTRO_ROOT/ros2_ws
   colcon build --symlink-install && source install/setup.bash
   ros2 launch astro_audio audio.launch.py

EOF
