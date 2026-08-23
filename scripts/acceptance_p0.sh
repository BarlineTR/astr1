#!/usr/bin/env bash
# ASTRO V1 — Spec #1 (Realtime S2S Ses Çekirdeği) Kapı 2 kabul betiği.
#
# Kullanım:
#   1) Robotu başlat ve log'u dosyaya yaz:
#        ros2 launch astro_bringup bringup.launch.py 2>&1 | tee /tmp/astro_run.log
#   2) Bir tur konuş, robotun sözünü kes (barge-in), "ne görüyorsun" diye sor,
#      bir bilgi kaydettir, "ileri git" de.
#   3) Bu betiği çalıştır:
#        ./scripts/acceptance_p0.sh /tmp/astro_run.log
set -uo pipefail

LOG="${1:-/tmp/astro_run.log}"
if [[ ! -f "$LOG" ]]; then
  echo "Log dosyası bulunamadı: $LOG" >&2
  echo "Kullanım: $0 <launch-log-dosyası>" >&2
  exit 2
fi

PASS=0
FAIL=0

check() {  # check <etiket> <grep-deseni>
  local label="$1" pattern="$2"
  if grep -qE -- "$pattern" "$LOG"; then
    printf '  \033[32mPASS\033[0m  %s\n' "$label"
    PASS=$((PASS + 1))
  else
    printf '  \033[31mFAIL\033[0m  %s\n' "$label"
    FAIL=$((FAIL + 1))
  fi
}

absent() {  # absent <etiket> <grep-deseni>
  local label="$1" pattern="$2"
  local n
  n=$(grep -cE -- "$pattern" "$LOG" || true)
  if [[ "$n" -eq 0 ]]; then
    printf '  \033[32mPASS\033[0m  %s (0 kez)\n' "$label"
    PASS=$((PASS + 1))
  else
    printf '  \033[31mFAIL\033[0m  %s (%s kez)\n' "$label" "$n"
    FAIL=$((FAIL + 1))
  fi
}

echo "AUDIO OWNERSHIP"
check "audio_input_owner=audio_stream_node"  "audio_input_owner=audio_stream_node"
check "audio_output_owner=audio_stream_node" "audio_output_owner=audio_stream_node"

echo "REALTIME"
check "session CONNECTED"       "REALTIME (SESSION READY|CONNECTING|CONNECTED)"
check "VAD yapılandırıldı"      "\[REALTIME VAD\]"
check "create_response=True"    "create_response=True"
check "interrupt_response=True" "interrupt_response=True"

echo "TURN"
check "speech_started"   "speech_started|Kullanıcı konuşmaya başladı"
check "speech_stopped"   "Cümle bitti"
check "response_created" "\[REALTIME RESPONSE CREATED\]"
check "audio_done"       "\[REALTIME AUDIO DONE\]"
check "response_done"    "\[REALTIME AUDIO SUMMARY\]"

echo "PLAYBACK"
check "first_audio_ms ölçüldü" "first_audio_ms=[0-9]"
if grep -qE "first_audio_ms=[0-9]" "$LOG"; then
  echo "        ölçülen değerler:"
  grep -oE "first_audio_ms=[0-9.]+" "$LOG" | sed 's/^/          /'
fi

echo "BARGE-IN"
check "barge-in algılandı" "Barge-In|Akustik Yankı Koruması"

echo "MOTION"
check "serial_connected"  "\[SERIAL CONNECTED\]|serial_connected=True"
check "handshake success" "\[ARDUINO HANDSHAKE\] status=success"
check "heartbeat ACK"     "\[HEARTBEAT ACK\]"
echo "  NOT: base_bridge yazılana kadar (Spec #2) move_robot'un"
echo "       'no_motion_backend' ile REDDETMESİ BEKLENEN davranıştır."

echo "VISION"
check "kamera tool çağrısı" "inspect_camera_view"

echo "MEMORY"
check "hafıza tool çağrısı" "save_user_memory|search_memory"

echo "NO ERRORS"
absent "Device busy"                              "Device or resource busy"
absent "write to closed file"                     "write to closed file"
absent "conversation_already_has_active_response" "conversation_already_has_active_response"
absent "response_cancel_not_active"               "response_cancel_not_active"

echo
echo "================================"
printf 'PASS: %s   FAIL: %s\n' "$PASS" "$FAIL"
echo "================================"
[[ "$FAIL" -eq 0 ]] || exit 1
