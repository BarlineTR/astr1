#!/usr/bin/env bash
# ASTRO V1 — Coqui XTTS v2 Production Installation & Hardware Setup
#
# Configures a 100% isolated persistent XTTS environment on Jetson Orin Nano / Linux:
#   - Target directory: ~/.astro/tts (or $TTS_XTTS_HOME)
#   - Python 3.10 virtual environment: ~/.astro/tts/.venv (ISOLATED, NO system-site-packages)
#   - Isolation flags: PYTHONPATH="" and PYTHONNOUSERSITE="1"
#   - Verified stack: Torch 2.8.0 / 2.5.1 with CUDA 12.6 on aarch64 (Orin GPU)
#   - Fixed packages: NumPy 1.26.4, SciPy 1.11.4, Librosa 0.10.2.post1, Numba 0.67.0, LLVMLite 0.49.0
#   - PyTorch 2.6+ / 2.8+ weights_only=False compatibility patch in TTS
#   - Reference speaker file provisioning (voices/astro.wav -> Recording.wav)
#   - Strict Acceptance Test verifying imports, CUDA GPU Orin residency, and model device.
#
# Usage:
#   ./scripts/install_xtts.sh
#
# Environment Overrides:
#   TTS_XTTS_HOME=/path/to/custom_home ./scripts/install_xtts.sh
#   XTTS_SKIP_DOWNLOAD=1 ./scripts/install_xtts.sh
set -euo pipefail

REPO_URL="${TTS_XTTS_REPO:-https://github.com/yunusemretom/TTS.git}"
XTTS_HOME="${TTS_XTTS_HOME:-$HOME/.astro/tts}"
PY_VERSION="3.10"

ASTRO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

say()  { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
ok()   { printf '\033[1;32m✅ %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m⚠️  %s\033[0m\n' "$*"; }
die()  { printf '\033[1;31m❌ %s\033[0m\n' "$*" >&2; exit 1; }

# ---------------------------------------------------------------- 1. Ön Koşullar
command -v git >/dev/null 2>&1 || die "git bulunamadı: sudo apt install -y git"

if ! command -v uv >/dev/null 2>&1; then
  say "uv yükleniyor..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi

export PATH="$HOME/.local/bin:$PATH"

if ! command -v espeak-ng >/dev/null 2>&1; then
  warn "espeak-ng yok — fonemleştirme için kurulması önerilir: sudo apt install -y espeak-ng"
fi

# ---------------------------------------------------------------- 2. Depo Yönetimi
mkdir -p "$XTTS_HOME"

if [ -d "$XTTS_HOME/.git" ]; then
  say "Mevcut Coqui TTS deposu güncelleniyor: $XTTS_HOME"
  git -C "$XTTS_HOME" fetch --depth 1 origin || warn "fetch başarısız, mevcut kopya kullanılıyor"
  git -C "$XTTS_HOME" reset --hard origin/HEAD 2>/dev/null || true
elif [ -f "$XTTS_HOME/setup.py" ]; then
  say "Mevcut TTS kaynak kodu kullanılıyor: $XTTS_HOME"
else
  say "Coqui TTS deposu indiriliyor: $REPO_URL -> $XTTS_HOME"
  TMP_CLONE_DIR="$(mktemp -d)"
  git clone --depth 1 "$REPO_URL" "$TMP_CLONE_DIR"
  cp -r "$TMP_CLONE_DIR"/. "$XTTS_HOME"/
  rm -rf "$TMP_CLONE_DIR"
fi

mkdir -p "$XTTS_HOME/voices"

cd "$XTTS_HOME"
VENV="$XTTS_HOME/.venv"
VPY="$VENV/bin/python"

# ---------------------------------------------------------------- 3. İzole Virtualenv Oluşturma
ARCH="$(uname -m)"
say "Sistem Mimarisi: $ARCH | Python Sürümü: $PY_VERSION"
say "İzole Sanal Ortam Hazırlanıyor (NO system-site-packages): $VENV"

if [ ! -x "$VPY" ]; then
  # STRICT ISOLATION: Never use --system-site-packages to avoid broken coverage/system packages
  uv venv --python "$PY_VERSION" "$VENV"
fi

# Set isolated environment variables
export PYTHONNOUSERSITE="1"
export PYTHONPATH=""

# ---------------------------------------------------------------- 4. PyTorch & CUDA Kurulumu
say "PyTorch ve CUDA 12.6 Stack Kurulumu Yapılıyor..."

if [ "$ARCH" = "aarch64" ]; then
  # Jetson Orin Nano (JetPack 6 / CUDA 12.6 cu126)
  say "Jetson Orin Nano aarch64 mimarisi için cu126 PyTorch kuruluyor..."
  VIRTUAL_ENV="$VENV" uv pip install \
    --extra-index-url "https://pypi.jetson-ai-lab.dev/jp6/cu126" \
    "torch==2.8.0" "torchaudio==2.8.0" 2>/dev/null || \
  VIRTUAL_ENV="$VENV" uv pip install \
    --extra-index-url "https://pypi.jetson-ai-lab.dev/jp6/cu126" \
    "torch" "torchaudio" || true
else
  # x86_64 Linux
  say "x86_64 mimarisi için CUDA 12.4 PyTorch kuruluyor..."
  VIRTUAL_ENV="$VENV" uv pip install \
    "torch==2.5.1+cu124" "torchaudio==2.5.1+cu124" \
    --extra-index-url "https://download.pytorch.org/whl/cu124" \
    --index-strategy unsafe-best-match || true
fi

# ---------------------------------------------------------------- 5. Sabit Paket Versiyonları
say "Doğrulanmış Production Paket Versiyonları Sabitleniyor..."
VIRTUAL_ENV="$VENV" uv pip install \
  "numpy==1.26.4" \
  "scipy==1.11.4" \
  "librosa==0.10.2.post1" \
  "numba==0.67.0" \
  "llvmlite==0.49.0" \
  "transformers==4.40.2" \
  "psutil"

say "Coqui TTS paketi kuruluyor..."
VIRTUAL_ENV="$VENV" uv pip install -e . --no-build-isolation 2>/dev/null || VIRTUAL_ENV="$VENV" uv pip install -e .

# ---------------------------------------------------------------- 6. Symlink ve NLTK
if command -v espeak-ng >/dev/null 2>&1; then
  ln -sf "$(command -v espeak-ng)" "$VENV/bin/espeak" || true
  ok "espeak symlink bağlandı: $VENV/bin/espeak"
fi

say "NLTK dil verileri indiriliyor..."
env PYTHONPATH="" PYTHONNOUSERSITE="1" "$VPY" -c \
  "import nltk; [nltk.download(p, quiet=True) for p in ['averaged_perceptron_tagger','averaged_perceptron_tagger_eng','punkt','cmudict']]" \
  || warn "NLTK verisi indirilemedi (varsayılan tokenizer kullanılacak)"

# ---------------------------------------------------------------- 7. PyTorch 2.6+ / 2.8+ weights_only=False Yaması
say "PyTorch 2.6+ / 2.8+ weights_only=False uyumluluk yaması uygulanıyor..."
env PYTHONPATH="" PYTHONNOUSERSITE="1" "$VPY" -c "
import os

tts_init_path = os.path.join('$XTTS_HOME', 'TTS', '__init__.py')
if os.path.exists(tts_init_path):
    with open(tts_init_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    patch_code = '''
# --- ASTRO V1 PyTorch 2.6+ weights_only=False compatibility monkeypatch ---
import torch
try:
    _orig_torch_load = torch.load
    def _astro_safe_torch_load(*args, **kwargs):
        if 'weights_only' not in kwargs:
            kwargs['weights_only'] = False
        return _orig_torch_load(*args, **kwargs)
    torch.load = _astro_safe_torch_load
except Exception:
    pass
# --------------------------------------------------------------------------
'''
    if 'ASTRO V1 PyTorch' not in content:
        with open(tts_init_path, 'w', encoding='utf-8') as f:
            f.write(patch_code + '\n' + content)
        print('  [PATCHED] TTS/__init__.py torch.load safely patched.')
    else:
        print('  [EXISTS] TTS/__init__.py patch already present.')
"

# ---------------------------------------------------------------- 8. Referans Ses Dosyası
SPEAKER_SRC="$ASTRO_ROOT/ros2_ws/src/astro_audio/voices/astro.wav"
SPEAKER_DST="$XTTS_HOME/Recording.wav"
SPEAKER_DST2="$XTTS_HOME/voices/astro.wav"

if [ -f "$SPEAKER_SRC" ]; then
  say "Referans ses dosyası senkronize ediliyor: $SPEAKER_SRC -> $SPEAKER_DST"
  cp -f "$SPEAKER_SRC" "$SPEAKER_DST"
  cp -f "$SPEAKER_SRC" "$SPEAKER_DST2"
  ok "Referans ses dosyası hazırlandı."
elif [ -f "$SPEAKER_DST" ]; then
  ok "Mevcut referans ses dosyası bulundu: $SPEAKER_DST"
else
  warn "Referans ses dosyası henüz yok."
fi

# ---------------------------------------------------------------- 9. Model Ön İndirme
if [ "${XTTS_SKIP_DOWNLOAD:-0}" != "1" ]; then
  say "Coqui XTTS v2 modeli indiriliyor (~1.8 GB, bir kez)..."
  env PYTHONPATH="" PYTHONNOUSERSITE="1" COQUI_TOS_AGREED=1 "$VPY" -c "
from TTS.utils.manage import ModelManager
ModelManager().download_model('tts_models/multilingual/multi-dataset/xtts_v2')
print('XTTS v2 model dosyaları hazır.')
" || warn "Model otomatik indirilemedi; acceptance test esnasında indirilecek."
fi

# ---------------------------------------------------------------- 10. KESİN ACCEPTANCE TESTİ
say "🔍 KESİN ACCEPTANCE TESTİ ÇALIŞTIRILIYOR..."

env PYTHONPATH="" PYTHONNOUSERSITE="1" COQUI_TOS_AGREED=1 "$VPY" -c "
import sys
print('1. İzole ortam kütüphane importları test ediliyor...')
import numba
print('   • numba          :', numba.__version__)
import librosa
from librosa import magphase, pyin
print('   • librosa        :', librosa.__version__, '(magphase, pyin OK)')
import torch
print('   • torch          :', torch.__version__)
import torchaudio
print('   • torchaudio     :', torchaudio.__version__)
import TTS
print('   • TTS            :', TTS.__version__)

print('2. CUDA ve Donanım Doğrulaması...')
if not torch.cuda.is_available():
    raise RuntimeError('FATAL: torch.cuda.is_available() is FALSE! GPU ortamı kurulamadı.')

gpu_name = torch.cuda.get_device_name(0)
print('   • CUDA Aygıtı    :', gpu_name)
cuda_ver = getattr(torch.version, 'cuda', 'unknown')
print('   • CUDA Sürümü    :', cuda_ver)

print('3. Modelin GPU Belleğine (cuda:0) Yüklenmesi...')
from TTS.api import TTS as CoquiTTS
tts = CoquiTTS('tts_models/multilingual/multi-dataset/xtts_v2').to('cuda')
param_device = next(tts.synthesizer.tts_model.parameters()).device
print('   • Model Parametre Cihazı:', param_device)

if 'cuda' not in str(param_device):
    raise RuntimeError(f'FATAL: Model parametreleri GPU\'da değil! ({param_device})')

print('4. Warm-Up Sentez Testi...')
test_wav = tts.tts(text='Astro robotu aktif.', language='tr', speaker_wav='$SPEAKER_DST')
assert len(test_wav) > 0, 'Sentezlenen ses verisi boş!'
print('   • Sentez Başarılı : {:d} örnek üretildi.'.format(len(test_wav)))
print('\n🎉 TÜM ACCEPTANCE TESTLERİ %100 BAŞARIYLA GEÇTİ!')
"

cat <<EOF

===========================================================================
 ✅ XTTS PRODUCTION KURULUMU & DONANIM DOĞRULAMASI TAMAMLANDI!
===========================================================================
   • XTTS Dizini      : $XTTS_HOME
   • Python Venv      : $VENV (İzole, PYTHONNOUSERSITE=1)
   • Referans Ses     : $SPEAKER_DST
   • CUDA GPU Durumu  : AKTİF (cuda:0, Warm & Resident)
   • Doğrulama Testi  : %100 BAŞARILI

   .env dosyanızda şu satırların bulunduğundan emin olun:
   TTS_XTTS_HOME="$XTTS_HOME"
   TTS_XTTS_SPEAKER_WAV="$SPEAKER_DST"
   TTS_XTTS_DEVICE="cuda"
   TTS_XTTS_HALF="1"

===========================================================================
EOF
