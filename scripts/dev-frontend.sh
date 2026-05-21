#!/usr/bin/env bash
# ForgeMind AI — start the Vite dev server for the frontend, no Docker required.
#
# The backend (api-gateway + LLM gateway + agent services) must be reachable
# somewhere. By default we look at http://localhost:8080 (the host port
# docker-compose maps api-gateway to). Override with VITE_API_URL.
#
# Usage:
#   ./scripts/dev-frontend.sh                       # uses http://localhost:8080
#   VITE_API_URL=http://api.example:8080 \
#     ./scripts/dev-frontend.sh                     # custom backend
#
# To run the backend services without the frontend container:
#   docker compose up -d $(docker compose config --services | grep -v frontend)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT/frontend"

VITE_API_URL="${VITE_API_URL:-http://localhost:8080}"

need() { command -v "$1" >/dev/null || { echo "ERROR: $1 not found in PATH"; exit 1; }; }
need node
need npm

echo "===================================================================="
echo "  ForgeMind frontend — Vite dev server (no Docker)"
echo "===================================================================="
echo "  node:         $(node --version)"
echo "  npm:          $(npm --version)"
echo "  api backend:  $VITE_API_URL"
echo

# Install deps on first run (or after package.json changes).
if [[ ! -d node_modules ]]; then
  echo "[1/2] Installing npm dependencies (first run)..."
  npm install --no-audit --no-fund
fi

# Best-effort backend reachability check — warn but don't fail; the user
# may be starting the backend in another terminal.
if command -v curl >/dev/null; then
  if curl -sf "${VITE_API_URL%/}/healthz" >/dev/null 2>&1 \
     || curl -sf "${VITE_API_URL%/}/api/v1/healthz" >/dev/null 2>&1 \
     || curl -sf "${VITE_API_URL%/}/" >/dev/null 2>&1; then
    echo "[ok]  api backend reachable at $VITE_API_URL"
  else
    echo "[warn] api backend at $VITE_API_URL is not responding."
    echo "       Start the backend with:  docker compose up -d \\"
    echo "       \$(docker compose config --services | grep -v frontend)"
    echo "       (proceeding anyway — proxy errors will appear until it's up)"
  fi
fi

echo
echo "[2/2] Starting Vite on http://localhost:5173 ..."
echo "      Stop with Ctrl+C."
echo
exec env VITE_API_URL="$VITE_API_URL" npm run start
