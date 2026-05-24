#!/usr/bin/env bash
# scripts/rebuild-frontend.sh
#
# Rebuild the frontend Docker image and force-recreate its container.
#
# Why: the frontend container is `node build → nginx serve` (multi-stage
# Dockerfile). The compiled dist/ is baked into the image at build time
# and there's no source volume mount, so changes to anything in
# frontend/src/ require a rebuild. `docker compose restart frontend`
# alone will keep serving the OLD bundle.
#
# Use this whenever you change frontend/src/** and want the change to
# show up at http://localhost:5173.
#
# For day-to-day development you can run `npm run dev` in frontend/
# directly (vite dev server on :5173 with HMR) — that's the
# recommended workflow and avoids needing this script altogether.
#
# Run from the repo root.

set -euo pipefail

cd "$(dirname "$0")/.."

echo "[1/3] Rebuilding frontend image (no cache)..."
docker compose build --no-cache frontend

echo "[2/3] Force-recreating frontend container..."
docker compose up -d --force-recreate frontend

echo "[3/3] Waiting for nginx to come up on http://localhost:5173 ..."
for i in 1 2 3 4 5 6 7 8 9 10; do
  CODE=$(curl -sS -o /dev/null -w "%{http_code}" http://localhost:5173/ || true)
  if [ "$CODE" = "200" ] || [ "$CODE" = "304" ]; then
    echo "  frontend healthy (HTTP $CODE)"
    break
  fi
  sleep 1
done

# Quick sanity check that the new bundle contains the new /login route.
# The compiled JS will reference Login.vue's chunk name. We check the
# served HTML's asset manifest for the login chunk.
echo "[3b/3] Checking served HTML references a login chunk..."
if curl -sS http://localhost:5173/ | grep -qiE 'login|auth'; then
  echo "  Looks fine (found auth-related markup or asset reference)."
else
  echo "  (Couldn't confirm via HTML — open http://localhost:5173/login in your browser to verify.)"
fi

echo
echo "Done. Open http://localhost:5173/login and sign in (defaults: admin / admin)."
echo "After signing in you'll be redirected to wherever you came from."
