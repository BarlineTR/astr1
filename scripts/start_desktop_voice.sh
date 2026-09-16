#!/usr/bin/env bash
# Starts the production ROS nodes directly from source, without robot hardware.
# Ctrl+C stops all children. Each node writes its own log under log/desktop-voice.
set -eo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
source /opt/ros/humble/setup.bash
export ASTRO_ENV_FILE="$ROOT/config/desktop-ollama.env"
set -a
source "$ASTRO_ENV_FILE"
set +a
export PYTHONPATH="$ROOT/ros2_ws/src/astro_ai:$ROOT/ros2_ws/src/astro_audio:$ROOT/ros2_ws/src/astro_vision:$ROOT/ros2_ws/src/astro_base:${PYTHONPATH:-}"
export PYTHONUNBUFFERED=1
export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-73}"
export ROS_LOCALHOST_ONLY=1
export FASTRTPS_DEFAULT_PROFILES_FILE="$ROOT/ros2_ws/src/astro_vision/config/fastdds_shm.xml"
unset ASTRO_TEST_MODE ASTRO_MOCK_AUDIO PYTEST_CURRENT_TEST
LOG_DIR="$ROOT/log/desktop-voice"
mkdir -p "$LOG_DIR"
export MEMORY_FILE_PATH="$LOG_DIR/memory.json"
export ASTRO_COGNITIVE_DB="$LOG_DIR/cognitive.db"
VPY="$ROOT/.venv/bin/python"
PIDS=()
cleanup() {
    trap - EXIT INT TERM
    for pid in "${PIDS[@]}"; do kill -INT "$pid" 2>/dev/null || true; done
    for pid in "${PIDS[@]}"; do wait "$pid" 2>/dev/null || true; done
}
trap cleanup EXIT INT TERM
start_node() {
    local label="$1"
    shift
    "$VPY" -m "$@" > "$LOG_DIR/$label.log" 2>&1 &
    PIDS+=("$!")
    echo "$label PID=$! log=$LOG_DIR/$label.log"
}
start_node brain astro_ai.astro_realtime_node --ros-args -p use_realtime:=false
start_node audio astro_audio.audio_stream_node --ros-args -p input_channels:=1 -p enable_hid_doa:=false
start_node camera astro_vision.webcam_publisher_node --ros-args -p device:=0
start_node vision astro_vision.face_detector_node
echo "Canlı ROS akışı başlatılıyor (domain $ROS_DOMAIN_ID). 'Hey Astro, nasılsın?' diye seslenin."
echo "Durum: tail -f $LOG_DIR/brain.log | Çıkış: Ctrl+C"
wait -n "${PIDS[@]}"
echo "Bir düğüm durdu; diğer düğümler kapatılıyor. Logları inceleyin."
exit 1
