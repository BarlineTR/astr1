#!/usr/bin/env bash
# ASTRO V1 — Yüz algılama/tanıma modelleri (OpenCV Zoo)
#
# Yüz tanıma için ek bir pip paketi gerekmez: YuNet ve SFace, kurulu
# opencv-python içindeki cv2.FaceDetectorYN / cv2.FaceRecognizerSF API'leriyle
# çalışır. Yalnızca bu iki ONNX dosyası indirilir (~37 MB).
set -euo pipefail

MODEL_DIR="${FACE_MODEL_DIR:-$HOME/.astro/models}"
BASE="https://github.com/opencv/opencv_zoo/raw/main/models"
YUNET_URL="$BASE/face_detection_yunet/face_detection_yunet_2023mar.onnx"
SFACE_URL="$BASE/face_recognition_sface/face_recognition_sface_2021dec.onnx"

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

say "Yüz modelleri: $MODEL_DIR"
fetch "$YUNET_URL" "$MODEL_DIR/yunet.onnx" "YuNet (algılama)"
fetch "$SFACE_URL" "$MODEL_DIR/sface.onnx" "SFace (tanıma)"

cat <<EOF

✅ Modeller hazır.

Kişi tanıtmak için:
   ./scripts/enroll_face.py --name Yunus --capture          # kameradan
   ./scripts/enroll_face.py --name Yunus --photos faces/Yunus   # fotoğraflardan
   ./scripts/enroll_face.py --list
EOF
