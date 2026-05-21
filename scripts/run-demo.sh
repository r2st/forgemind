#!/usr/bin/env bash
# End-to-end demo: inject anomalies, wait for detection, run RCA via the
# investigation workflow, generate an executive report.
set -euo pipefail

API="${API:-http://localhost:8080/api/v1}"

echo "==> Injecting historical anomaly wave"
curl -s -X POST "$API/replay-historical" | jq .

echo "==> Sleeping 30s for the anomaly engine to fire incidents"
sleep 30

echo "==> Listing recent incidents"
INC=$(curl -s "$API/incidents?limit=5")
echo "$INC" | jq '.[0:3]'
INC_ID=$(echo "$INC" | jq -r '.[0].incident_id')
echo "First incident: $INC_ID"

echo "==> Running LangGraph investigation workflow"
curl -s -X POST "$API/workflows/investigation/run" \
  -H "Content-Type: application/json" \
  -d "{\"incident_id\":\"$INC_ID\",\"approved\":true}" | jq '.status, .state.severity, .state.recommendations'

echo "==> Generating executive report"
curl -s -X POST "$API/reports/generate" \
  -H "Content-Type: application/json" \
  -d '{"kind":"executive"}' | jq '.title, .body[0:400]'

echo "==> Asking ChatOps for a summary"
curl -s -X POST "$API/chat" \
  -H "Content-Type: application/json" \
  -d '{"session_id":"demo","message":"What were the top 3 incidents in the last hour and what should we do?"}' \
  | jq '.response'

echo "==> Done."
