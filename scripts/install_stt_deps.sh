#!/usr/bin/env bash
# ASTRO V1 — Faster-Whisper ve ses pipeline Python bağımlılıkları
set -euo pipefail

echo "==> Faster-Whisper ve ses bağımlılıkları kuruluyor..."

pip3 install --upgrade pip
pip3 install \
  faster-whisper \
  edge-tts \
  requests \
  python-dotenv \
  openai \
  vosk \
  sounddevice \
  numpy

# GPU var mı?
if command -v nvidia-smi >/dev/null 2>&1; then
  echo ""
  echo "✅ NVIDIA GPU algılandı. .env dosyanızda şunları kullanın:"
  echo '   STT_FW_DEVICE="cuda"'
  echo '   STT_FW_COMPUTE_TYPE="float16"'
else
  echo ""
  echo "⚠️  NVIDIA GPU bulunamadı. .env dosyanızda CPU ayarlarını kullanın:"
  echo '   STT_FW_DEVICE="cpu"'
  echo '   STT_FW_COMPUTE_TYPE="int8"'
  echo '   STT_FW_MODEL="small"   # CPU için daha hızlı (isteğe bağlı)'
fi

echo ""
echo "==> Kurulum testi..."
python3 -c "from faster_whisper import WhisperModel; print('✅ faster-whisper import OK')"

echo ""
echo "Tamamlandı. Yeniden derleyip launch edin:"
echo "  cd ~/Desktop/astr1/ros2_ws && colcon build --symlink-install && source install/setup.bash"
echo "  ros2 launch astro_bringup robot.launch.py"
