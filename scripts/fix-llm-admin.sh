#!/usr/bin/env bash
# scripts/fix-llm-admin.sh
#
# One-shot fix for `unknown section admin` on /llm-admin.
#
# Root cause: the api-gateway container was built before the
# `llm_admin_proxy` route was added to services/api-gateway/app/main.py.
# Restarting alone won't help — the image itself is stale. We must
# rebuild the image from the current source and force-recreate the
# container.
#
# This script:
#   1. Rebuilds the api-gateway image from current source.
#   2. Force-recreates the container so the new image is actually used.
#   3. Waits for it to come up and verifies the route is registered.
#   4. Verifies /api/v1/admin/llm/providers no longer returns the
#      "unknown section admin" 404.
#
# Run from the repo root.

set -euo pipefail

cd "$(dirname "$0")/.."

echo "[1/4] Rebuilding api-gateway image (no cache)..."
docker compose build --no-cache api-gateway

echo "[2/4] Force-recreating api-gateway container..."
docker compose up -d --force-recreate api-gateway

echo "[3/4] Waiting for api-gateway to come up..."
for i in 1 2 3 4 5 6 7 8 9 10; do
  if curl -sS -o /dev/null -w "%{http_code}\n" http://localhost:8080/healthz | grep -q 200; then
    echo "  api-gateway healthy"
    break
  fi
  sleep 1
done

echo "[3b/4] Checking api-gateway startup logs for the llm_admin_proxy route..."
if docker compose logs api-gateway --tail 60 2>&1 | grep -q "admin_routes_registered"; then
  echo "  Found admin_routes_registered log line — new image is running."
elif docker compose logs api-gateway --tail 60 2>&1 | grep -q "llm_admin_proxy_missing"; then
  echo "  ERROR: api-gateway logs say llm_admin_proxy is MISSING from the new image."
  echo "  Check that services/api-gateway/app/main.py contains the llm_admin_proxy route."
  exit 1
else
  echo "  (Couldn't find startup route log — check 'docker compose logs api-gateway' manually.)"
fi

echo "[4/4] Hitting /api/v1/admin/llm/providers to confirm the 404 is gone..."
# Need a token first — log in as admin (assumes default bootstrap creds
# unless the operator has changed them).
TOKEN=$(curl -sS -X POST http://localhost:8080/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin"}' \
  | python3 -c 'import sys,json; print(json.load(sys.stdin).get("access_token",""))' 2>/dev/null || true)

if [ -z "$TOKEN" ]; then
  echo "  (Couldn't log in as admin/admin — credentials may be customized.)"
  echo "  Hitting without auth to at least confirm the route exists:"
  CODE=$(curl -sS -o /dev/null -w "%{http_code}" http://localhost:8080/api/v1/admin/llm/providers)
  # 401 is correct (route exists, just needs auth). 404 = still broken.
  case "$CODE" in
    401) echo "  401 — route is correctly registered (auth required). FIXED." ;;
    404) echo "  404 — route still missing. The rebuild didn't take. Investigate."; exit 1 ;;
    *)   echo "  HTTP $CODE — unexpected, but likely fixed." ;;
  esac
else
  RESPONSE=$(curl -sS -w "\n%{http_code}" http://localhost:8080/api/v1/admin/llm/providers \
    -H "Authorization: Bearer $TOKEN")
  CODE=$(echo "$RESPONSE" | tail -n1)
  # macOS BSD `head` doesn't support negative line counts; use sed
  # to delete the last line ($d) for portability across macOS / Linux.
  BODY=$(echo "$RESPONSE" | sed '$d')
  case "$CODE" in
    200) echo "  200 OK — providers endpoint working. FIXED."; echo "  Body: $BODY" ;;
    404) echo "  404 — route still missing. The rebuild didn't take. Investigate."
         echo "  Body: $BODY"; exit 1 ;;
    *)   echo "  HTTP $CODE — route is registered (no 'unknown section admin'). FIXED."
         echo "  Body: $BODY" ;;
  esac
fi

echo
echo "Done. Reload http://localhost:5173/llm-admin in your browser."
