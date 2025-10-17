#!/bin/bash
set -e

# --- Configuration ---
BASE_DIR="$HOME/funmcp"
LOG_DIR="$BASE_DIR/logs"
VENV_BIN="$BASE_DIR/.venv/bin"
FASTMCP="$VENV_BIN/fastmcp"

# --- Ensure log directory exists ---
mkdir -p "$LOG_DIR"

echo "[+] Stopping any existing funmcp servers..."
# Kill all running fastmcp processes under funmcp
pkill -f "$FASTMCP" || true
sleep 2

echo "[+] Starting funmcp servers..."

run_server() {
    local script="$1"
    local port="$2"
    local name
    name=$(basename "$script" .py)

    echo "  → Starting $name on port $port"
    setsid "$VENV_BIN/python3" "$FASTMCP" run "servers/$script:mcp" \
        --transport http --port "$port" \
        >"$LOG_DIR/${name}.log" 2>&1 &
}

# Start all servers
run_server "old_image_reviver.py" 9001
run_server "grayscale_server.py" 9002
run_server "ai-upscale.py" 9003
run_server "audio_clone_server.py" 9004
run_server "product_photoshoot_server.py" 9005
run_server "try_fashion.py" 9006
run_server "meshy_text_to_3d_server.py" 9007
run_server "background_replace_server.py" 9008
run_server "video_background_removal_server.py" 9009
run_server "genfill_server.py" 9010
run_server "texture_generator_server.py" 9012
run_server "fake_progress.py" 9013

echo "[✓] All funmcp servers started successfully."
