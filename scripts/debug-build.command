#!/usr/bin/env bash
# Debug build for chatops-service with full pip output saved to the project folder.
cd "$(dirname "$0")/.."
clear
LOG="$(pwd)/build-debug.log"
echo "=== Debug build: chatops-service with plain output ==="
echo "Saving full log to: $LOG"
echo
DOCKER_BUILDKIT=1 docker compose build --progress=plain --no-cache chatops-service > "$LOG" 2>&1
ec=$?
echo "Build exit code: $ec"
echo
echo "Last 80 lines of log:"
tail -80 "$LOG"
echo
echo "(Full log: $LOG)"
echo "Press any key to close..."
read -n 1
