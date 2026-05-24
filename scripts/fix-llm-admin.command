#!/usr/bin/env bash
# Double-click this file in Finder to fix the "unknown section admin"
# error on http://localhost:5173/llm-admin.
#
# What it does:
#   1. cds to the repo root (the parent of this scripts/ folder).
#   2. Runs scripts/fix-llm-admin.sh, which rebuilds the api-gateway
#      Docker image from the current source and force-recreates the
#      container so the llm_admin_proxy route actually loads.
#
# Why .command: macOS Terminal executes .command files when you
# double-click them in Finder. No need to open a terminal manually.

set -e

# Resolve the directory this file lives in, then go up one to repo root.
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$HERE/.." && pwd)"

cd "$REPO_ROOT"

echo "Running fix-llm-admin from: $REPO_ROOT"
echo

bash scripts/fix-llm-admin.sh

echo
echo "---"
echo "Done. Reload http://localhost:5173/llm-admin in your browser."
echo "You can close this window."
