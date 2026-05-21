#!/usr/bin/env bash
# Recreate all ForgeMind containers with the Knol .env (docker compose restart
# alone does NOT re-read .env — you have to `up -d` so containers are recreated).
set -e
cd "$(dirname "$0")/.."
clear
echo "===================================================================="
echo "  Switching ForgeMind to the Knol TrueFoundry tenant"
echo "===================================================================="
echo
echo "Current .env (TFY lines):"
grep -E '^TFY_GATEWAY_BASE_URL|^TFY_CONTROL_PLANE_URL|^TFY_MODEL_FAST|^TFY_WORKSPACE' .env
echo
echo "Recreating Hermes-using containers so they pick up the new .env..."
docker compose up -d --force-recreate \
  anomaly-detection rca-service ai-orchestrator workflow-engine \
  chatops-service reporting-service notification-service api-gateway
echo
echo "Sleeping 8s for containers to become ready..."
sleep 8

echo
echo "Triggering a chat call so a trace lands on Knol Request Traces page..."
RESP=$(curl -s -X POST "http://localhost:8080/api/v1/chat" \
  -H "Content-Type: application/json" \
  -d '{"session_id":"knol-trace-'$(date +%s)'","message":"Which machine is most at risk right now?"}')
echo "$RESP" | python3 -m json.tool | head -20

echo
echo "Model used (should be aws-bedrock/global.anthropic.claude-opus-4-7):"
echo "$RESP" | python3 -c "import sys,json; d=json.load(sys.stdin); print('  ' + str(d.get('model_used')))"

echo
echo "Now check Knol Request Traces:"
echo "  https://knol.truefoundry.cloud/monitoring/request-traces"
echo
echo "Press any key to close..."
read -n 1
