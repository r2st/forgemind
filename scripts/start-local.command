#!/usr/bin/env bash
# Wrapper that lets you double-click in Finder to launch the stack in Terminal.
cd "$(dirname "$0")/.."
clear
echo "===================================================================="
echo "  ForgeMind AI — launching local stack"
echo "  (you can close this window when done, then 'docker compose down')"
echo "===================================================================="
echo
exec ./scripts/start-local.sh
