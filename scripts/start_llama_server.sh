#!/usr/bin/env bash
# ASTRO V1 — Local Gemma 4 E2B Q4_K_S llama-server Runner

set -e
export GGML_CUDA_ENABLE_UNIFIED_MEMORY=1

# 1. Resolve llama-server binary
LLAMA_SERVER_BIN=""
CANDIDATES=(
    "$HOME/Desktop/llama.cpp/build/bin/llama-server"
    "$HOME/Desktop/llama.cpp/llama-server"
    "$HOME/Desktop/llama.cpp/build/bin/server"
    "$HOME/llama.cpp/build/bin/llama-server"
    "$(which llama-server 2>/dev/null || true)"
)

for c in "${CANDIDATES[@]}"; do
    if [ -n "$c" ] && [ -x "$c" ]; then
        LLAMA_SERVER_BIN="$c"
        break
    fi
done

if [ -z "$LLAMA_SERVER_BIN" ]; then
    echo "❌ [HATA] llama-server ikilisi bulunamadı!"
    echo "Lütfen llama.cpp'nin derlendiğinden emin olun: cd ~/Desktop/llama.cpp && cmake -B build && cmake --build build --config Release -j\$(nproc)"
    exit 1
fi

# 2. Resolve Gemma model
MODEL_PATH=""
if [ -n "$1" ] && [ -f "$1" ]; then
    MODEL_PATH="$1"
else
    # Search common HuggingFace cache and Desktop paths
    MODEL_CANDIDATES=(
        "$HOME/.cache/huggingface/hub/models--unsloth--gemma-4-E2B-it-GGUF/snapshots/0314792d7f1f7e229411f620751375812bb9faf2/gemma-4-E2B-it-Q4_K_S.gguf"
        "$HOME/Desktop/gemma-4-E2B-it-Q4_K_S.gguf"
        "$HOME/models/gemma-4-E2B-it-Q4_K_S.gguf"
        "$(find $HOME/.cache/huggingface -name '*gemma-4*Q4_K_S.gguf' 2>/dev/null | head -n 1)"
    )

    for m in "${MODEL_CANDIDATES[@]}"; do
        if [ -n "$m" ] && [ -f "$m" ]; then
            MODEL_PATH="$m"
            break
        fi
    done
fi

if [ -z "$MODEL_PATH" ]; then
    echo "❌ [HATA] gemma-4-E2B-it-Q4_K_S.gguf modeli bulunamadı!"
    echo "Kullanım: ./scripts/start_llama_server.sh /yol/to/model.gguf"
    exit 1
fi

echo "============================================================================"
echo " 🚀 ASTRO LOCAL GEMMA 4 E2B Q4_K_S — LLAMA-SERVER BAŞLATILIYOR"
echo "============================================================================"
echo "  İkili (Binary) : $LLAMA_SERVER_BIN"
echo "  Model          : $MODEL_PATH"
echo "  Uç Nokta       : http://127.0.0.1:8080/completion"
echo "  Sağlık Uç Nokta: http://127.0.0.1:8080/health"
echo "  GPU Katmanları : -ngl 32 (Tam Orin GPU Hızlandırma)"
echo "  Bağlam (Ctx)   : 512"
echo "============================================================================"
echo ""

echo
echo "🧹 Jetson page cache temizleniyor..."
sudo sync
echo 3 | sudo tee /proc/sys/vm/drop_caches >/dev/null
echo "✅ Page cache temizlendi."
echo
exec "$LLAMA_SERVER_BIN" \
    -m "$MODEL_PATH" \
    --port 8080 \
    --host 127.0.0.1 \
    -c 512 \
    -b 128 \
    -ub 128 \
    -ngl 32 \
    --fit off \
    --cache-ram 0 \
    --no-warmup \
    --no-op-offload
