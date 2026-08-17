#!/usr/bin/env bash
# ASTRO V1 — Yüz ve ses tanıma modelleri
#
# Ek pip paketi gerekmez: yüz tarafı kurulu opencv-python'daki
# cv2.FaceDetectorYN / cv2.FaceRecognizerSF ile, ses tarafı faster-whisper ile
# birlikte gelen onnxruntime ile çalışır. Yalnızca üç ONNX dosyası indirilir (~63 MB).
set -euo pipefail

MODEL_DIR="${FACE_MODEL_DIR:-$HOME/.astro/models}"
BASE="https://github.com/opencv/opencv_zoo/raw/main/models"
YUNET_URL="$BASE/face_detection_yunet/face_detection_yunet_2023mar.onnx"
SFACE_URL="$BASE/face_recognition_sface/face_recognition_sface_2021dec.onnx"
# Sesten kişi tanıma (WeSpeaker ResNet34, VoxCeleb) — onnxruntime zaten kurulu
SPEAKER_URL="https://huggingface.co/Wespeaker/wespeaker-voxceleb-resnet34-LM/resolve/main/voxceleb_resnet34_LM.onnx"

say() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
die() { printf '\033[1;31m❌ %s\033[0m\n' "$*" >&2; exit 1; }

command -v curl >/dev/null 2>&1 || die "curl bulunamadı: sudo apt install curl"
mkdir -p "$MODEL_DIR"

fetch() {
  local url="$1" out="$2" label="$3"
  if [ -s "$out" ]; then
    printf '   ✓ %s zaten var (%s)\n' "$label" "$(du -h "$out" | cut -f1)"
    return
  fi
  printf '   ↓ %s indiriliyor...\n' "$label"
  curl -fL --progress-bar -o "$out" "$url" || die "$label indirilemedi: $url"
  printf '   ✓ %s (%s)\n' "$label" "$(du -h "$out" | cut -f1)"
}

say "Tanıma modelleri: $MODEL_DIR"
fetch "$YUNET_URL" "$MODEL_DIR/yunet.onnx" "YuNet (algılama)"
fetch "$SFACE_URL" "$MODEL_DIR/sface.onnx" "SFace (yüz tanıma)"
fetch "$SPEAKER_URL" "$MODEL_DIR/speaker_resnet34.onnx" "WeSpeaker (ses tanıma)"

cat <<EOF

✅ Modeller hazır.

Kişi tanıtmak için:
   ./scripts/enroll_face.py    --name Yunus --capture              # yüz, kameradan
   ./scripts/enroll_face.py    --name Yunus --photos faces/Yunus   # yüz, fotoğraflardan
   ./scripts/enroll_speaker.py --name Yunus --record               # ses, mikrofondan
   ./scripts/enroll_face.py --list ; ./scripts/enroll_speaker.py --list
EOF
