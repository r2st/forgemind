#!/usr/bin/env bash
# Deploy ForgeMind AI to TrueFoundry.
#
# Requires:
#   pip install truefoundry
#   tfy login  (or TFY_API_KEY env var)
#
# Env vars:
#   TFY_HOST       e.g. https://app.truefoundry.com
#   TFY_API_KEY    your personal access token
#   TFY_WORKSPACE  workspace name (e.g. forgemind-prod)
#   TFY_DOMAIN     e.g. tfy.yourcompany.com
#   TFY_CLUSTER    optional, default 'default'
set -euo pipefail

: "${TFY_HOST:?must set TFY_HOST}"
: "${TFY_API_KEY:?must set TFY_API_KEY}"
: "${TFY_WORKSPACE:?must set TFY_WORKSPACE}"
: "${TFY_DOMAIN:=tfy.example.com}"

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
ROOT=$(cd "$SCRIPT_DIR/../.." && pwd)
cd "$ROOT"

echo "→ Logging into TrueFoundry"
tfy config set host "$TFY_HOST"
echo "$TFY_API_KEY" | tfy login --api-key-stdin || true

echo "→ Creating workspace if missing"
envsubst < "$SCRIPT_DIR/workspace.yaml" | tfy apply -f - || true

echo "→ Applying AI Gateway routing config"
tfy apply -f "$SCRIPT_DIR/gateway/routing.yaml" --workspace "$TFY_WORKSPACE"

echo "→ Creating secrets in the workspace"
tfy secrets create tfy-gateway-key  --workspace "$TFY_WORKSPACE" --value "$TFY_API_KEY"   --update || true
tfy secrets create jwt-secret       --workspace "$TFY_WORKSPACE" --value "${JWT_SECRET:-change-me-prod}" --update || true
if [[ -n "${OPENAI_API_KEY:-}" ]]; then
  tfy secrets create openai-api-key --workspace "$TFY_WORKSPACE" --value "$OPENAI_API_KEY" --update || true
fi
if [[ -n "${ANTHROPIC_API_KEY:-}" ]]; then
  tfy secrets create anthropic-api-key --workspace "$TFY_WORKSPACE" --value "$ANTHROPIC_API_KEY" --update || true
fi

echo "→ Deploying services"
SERVICES=(
  api-gateway telemetry-simulator telemetry-ingestion anomaly-detection
  rca-service predictive-maintenance ai-orchestrator workflow-engine
  chatops-service reporting-service notification-service frontend
)
for svc in "${SERVICES[@]}"; do
  echo "  -> $svc"
  envsubst < "$SCRIPT_DIR/services/${svc}.yaml" | tfy apply -f - --workspace "$TFY_WORKSPACE"
done

echo "→ Done. Public URLs:"
for svc in "${SERVICES[@]}"; do
  echo "   https://${svc}-${TFY_WORKSPACE}.${TFY_DOMAIN}"
done
echo
echo "Frontend:  https://forgemind-${TFY_WORKSPACE}.${TFY_DOMAIN}"
