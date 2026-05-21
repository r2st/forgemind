# API Reference

All routes are exposed via the API gateway at `http://localhost:8080/api/v1/...` in dev, or through your configured production ingress.

## Auth

```
POST /auth/login            { username, password }    → { access_token, role }
GET  /auth/me                                         → current identity
```

Demo accounts: `admin/admin`, `engineer/engineer`, `operator/operator`, anything else with password `viewer`.

## Telemetry

```
GET  /machines                                        → list machines + state
GET  /snapshot                                        → live telemetry for all machines
POST /inject               { machine_id, kind, duration_ticks } → start anomaly
POST /replay-historical                               → preset wave of anomalies for the demo
POST /telemetry/batch      { readings: [...] }        → bulk HTTP ingest
POST /telemetry/single     { reading }                → single HTTP ingest
GET  /telemetry/health                                → ingest counters
```

Anomaly kinds: `vibration_spike`, `thermal_runaway`, `pressure_drop`, `motor_stall`, `quality_spike`, `power_surge`.

## Incidents

```
GET  /incidents?machine_id=&severity=&limit=          → recent incidents
POST /incidents/score      { TelemetryReading }       → score one reading without publishing
```

## RCA

```
POST /rca/run              { incident_id, extra_context? }   → run Hermes RCA Agent
GET  /rca/reports?limit=                                     → list reports
GET  /rca/reports/{report_id}                                → one report
```

Response shape:

```json
{
  "report_id": "...",
  "summary": "...",
  "findings": [{"category": "MECHANICAL", "hypothesis": "...", "evidence": ["..."], "likelihood": 0.78}],
  "recommended_actions": ["..."],
  "confidence": 0.82,
  "similar_incidents": ["..."],
  "model_used": "anthropic-main/claude-sonnet-4-5",
  "cost_usd": 0.0123
}
```

## Predictive Maintenance

```
GET  /predictions                                            → all machines, sorted by risk_72h
GET  /predictions/{machine_id}                               → one machine
POST /predictions/explain/{machine_id}                       → narrative via Hermes PdM Agent
```

## Workflows (LangGraph)

```
GET  /workflows                                              → list workflow graphs + node lists
POST /workflows/{name}/run    { incident_id?, machine_id?, operator_note?, approved? }
GET  /workflows/runs?limit=&name=                            → run history
GET  /workflows/runs/{run_id}                                → one run
```

Workflows: `investigation`, `maintenance_approval`, `remediation`, `escalation`.

The `state.trace[]` in a run response shows each node that fired with its key outputs — handy for the AI Agent Activity UI.

## Agents (Hermes Orchestrator)

```
GET  /agents                                                 → list specialists
POST /agents/run              { task, history?, task_id? }   → supervisor run
GET  /agents/activity?limit=&agent_name=                     → recent agent runs across the platform
```

## Chat

```
POST /chat                    { session_id?, message }       → synchronous reply
POST /chat/stream             { session_id?, message }       → SSE: events `start | tool | token | done`
GET  /chat/sessions/{session_id}                             → message history
```

## Reports

```
POST /reports/generate        { kind: "shift" | "executive" | "daily", title? }
GET  /reports?limit=                                         → list reports
GET  /reports/{report_id}                                    → one report
```

## Notifications

```
GET  /notifications/recent?limit=                            → recent alerts (after suppression)
```

## Observability

Every service exposes:

- `GET /healthz`     liveness
- `GET /readyz`      readiness
- `GET /metrics`     Prometheus
