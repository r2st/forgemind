#!/usr/bin/env bash
# ForgeMind AI — one-shot local launcher.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

need() { command -v "$1" >/dev/null || { echo "ERROR: $1 not found in PATH"; exit 1; }; }
need docker
docker info >/dev/null 2>&1 || { echo "ERROR: Docker Desktop is not running. Start it first."; exit 1; }
if ! docker compose version >/dev/null 2>&1; then
  echo "ERROR: 'docker compose' plugin missing."
  exit 1
fi
if [[ ! -f .env ]]; then
  echo "ERROR: .env is missing."
  exit 1
fi

echo "===================================================================="
echo "  ForgeMind AI — local stack"
echo "===================================================================="
echo "Docker:        $(docker --version | head -1)"
echo "Compose:       $(docker compose version --short)"
echo "Workspace:     $ROOT"
echo

echo "[1/4] Building images (first run ~3 min; full output below)..."
echo "----------------------------------------------------------------"
if ! docker compose build --parallel 2>&1; then
  echo
  echo "================================================================"
  echo "  BUILD FAILED — see output above. Common fixes:"
  echo "    - missing build-essential / gcc in a Dockerfile"
  echo "    - a requirements.txt typo"
  echo "    - network blip pulling pip/git deps  (re-run to retry)"
  echo "================================================================"
  exit 1
fi
echo "----------------------------------------------------------------"

echo
echo "[2/4] Bringing the stack up in the background..."
docker compose up -d 2>&1

echo
echo "[3/4] Waiting for services to become healthy..."
TARGETS=(
  "api-gateway:8080"
  "telemetry-simulator:8001"
  "anomaly-detection:8003"
  "rca-service:8004"
  "predictive-maintenance:8005"
  "ai-orchestrator:8006"
  "workflow-engine:8007"
  "chatops-service:8008"
  "reporting-service:8009"
  "notification-service:8010"
)
fail=0
for t in "${TARGETS[@]}"; do
  name="${t%%:*}"; port="${t##*:}"
  printf "  - %-25s " "$name"
  ok=0
  for i in $(seq 1 90); do
    if curl -sf "http://localhost:${port}/healthz" >/dev/null 2>&1; then
      echo "OK"
      ok=1
      break
    fi
    sleep 1
  done
  if [[ $ok -eq 0 ]]; then
    echo "TIMEOUT"
    fail=$((fail+1))
    echo "      last 10 lines of $name:"
    docker compose logs --tail 10 "$name" 2>&1 | sed 's/^/        /'
  fi
done

if [[ $fail -gt 0 ]]; then
  echo
  echo "$fail service(s) didn't start. Stack is partially up — check 'docker compose ps'."
  echo "Skipping demo; fix the failing services and re-run."
  exit 1
fi

echo
echo "[4/4] Driving the demo flow..."
./scripts/run-demo.sh 2>&1 | sed 's/^/  /'

echo
echo "===================================================================="
echo "  Stack is up."
echo "===================================================================="
echo "  Dashboard:   http://localhost:5173"
echo "  API:         http://localhost:8080"
echo "  Grafana:     http://localhost:3000   (admin / admin)"
echo "  Prometheus:  http://localhost:9090"
echo
echo "  Stop:        docker compose down"
echo "  Stop+wipe:   docker compose down -v"
