#!/usr/bin/env bash
# Double-click in Finder to rebuild the frontend container and
# pick up the new login flow.
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$HERE/.." && pwd)"
cd "$REPO_ROOT"
echo "Running rebuild-frontend from: $REPO_ROOT"
echo
bash scripts/rebuild-frontend.sh
echo
echo "Done. You can close this window."
