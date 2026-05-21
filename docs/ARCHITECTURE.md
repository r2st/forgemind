# ForgeMind AI — Architecture

## The triad

ForgeMind is built on three layers with sharply distinct responsibilities. Getting the boundaries right is what makes the platform feel coherent rather than a pile of frameworks glued together.

```
┌──────────────────────────────────────────────────────────────────────┐
│                            LangGraph                                 │
│         Deterministic stateful workflow control plane                │
│   (investigation, maintenance_approval, remediation, escalation)     │
└──────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
┌──────────────────────────────────────────────────────────────────────┐
│                          Hermes Agents                               │
│   Autonomous intelligence + tool use + persistent memory             │
│   Monitoring · RCA · PdM · Optimization · Reporting · ChatOps · Supv │
└──────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
┌──────────────────────────────────────────────────────────────────────┐
│                    OpenAI-Compatible LLM API                         │
│   Configured base URL · API key · model tiers · optional gateway     │
│   Direct provider, private proxy, or self-hosted compatible API      │
└──────────────────────────────────────────────────────────────────────┘
```

Hermes routes every LLM call through the configured OpenAI-compatible API
(`base_url` + `api_key`). LangGraph calls Hermes agents as nodes. The Admin
Panel can override base URL, model, API key, and enabled state per agent.

## Service map

```
                                ┌───────────────────────┐
              telemetry stream  │  telemetry-simulator  │  ◄── inject anomalies
              ──────────────►   └──────────┬────────────┘
                                           │  NATS  forgemind.telemetry
                                           ▼
                                ┌───────────────────────┐
                                │  anomaly-detection     │  (stat + iforest + LLM severity)
                                └──────────┬─────────────┘
                                           │  Postgres write +
                                           │  NATS forgemind.incidents
                                           ▼
                          ┌────────────────────────────────┐
                          │  notification-service          │  (adaptive suppression)
                          └────────────────────────────────┘
                                           │
                                           ▼
                          ┌────────────────────────────────┐
   operator clicks RCA   ─▶  workflow-engine (LangGraph)   │  graphs: investigation,
                          │  ┌─────┐ ┌─────┐ ┌─────┐ ...   │          maintenance_approval,
                          │  │node │ │node │ │node │       │          remediation, escalation
                          │  └──┬──┘ └──┬──┘ └──┬──┘       │
                          └─────┼───────┼───────┼──────────┘
                                ▼       ▼       ▼
                       ┌─────────────┐ ┌─────────────────┐ ┌─────────────────────┐
                       │ rca-service │ │ pdm-service     │ │ ai-orchestrator     │
                       │ Hermes RCA  │ │ Hermes PdM      │ │ Hermes Supervisor   │
                       │ + pgvector  │ │ + analytical    │ │ + specialists       │
                       └──────┬──────┘ └────────┬────────┘ └──────────┬──────────┘
                              │                 │                     │
                              ▼                 ▼                     ▼
                       ┌──────────────────────────────────────────────────────┐
                       │  Configured OpenAI-Compatible API                    │
                       │  (direct provider, private gateway, or self-hosted   │
                       │   compatible endpoint)                               │
                       └──────────────────────────────────────────────────────┘
```

## The investigation workflow (LangGraph)

The flagship flow. One incident in, one closed-loop investigation out.

```
fetch_incident ─► fetch_telemetry ─► run_rca ─► run_pdm ─► assess_severity ─► approval_gate ──► notify ─► END
                                                                                       │
                                                                                       └─► wait_for_approval (END)
```

Each node mutates a shared `WorkflowState`. The `assess_severity` node combines incident severity, PdM 72h risk, and RCA confidence. `approval_gate` is the human-in-the-loop seam: HIGH/CRITICAL outcomes block on approval; the graph pauses, persists, and resumes when an operator clicks Approve.

## Hermes agent topology

| Agent | Tier | Tools | Memory |
| ---- | ---- | ----- | ------ |
| Supervisor | POWERFUL | `delegate_to_agent`, `list_specialists` | session |
| Monitoring | FAST | `list_recent_incidents`, `get_machine_snapshot` | session |
| RCA | POWERFUL | `get_incident`, `get_telemetry_context`, `search_similar_incidents` (pgvector), `record_incident_memory` | pgvector persistent |
| PdM | POWERFUL | `recent_incidents_for_machine`, `get_machine_snapshot` | session |
| Optimization | POWERFUL | `get_machine_snapshot`, `list_recent_incidents` | session |
| Reporting | POWERFUL | `list_recent_incidents`, `list_recent_rca` | session |
| ChatOps | POWERFUL | `query_incidents`, `get_machine_telemetry`, `run_rca`, `ask_supervisor`, `list_agent_activity` | session |
| Remediation | FAST | (LLM-only) | session |

The RCA Agent is the only one that writes durable agent memory (vector summaries of past incidents). All other operational state lives in the relational store; pgvector is reserved for semantic recall.

## LLM API Model Tiers

Hermes asks for a *tier*; the runtime maps that tier to a concrete model. The
Admin Panel can override the model globally or per agent.

| Tier | Default model | Used by |
| ---- | ------------- | ------- |
| `fast` | `gpt-4o-mini` | severity classifier, remediation agent, monitoring agent |
| `powerful` | `gpt-4o` | RCA, PdM, supervisor, reporting, chatops |
| `fallback` | `gpt-4o-mini` | last-resort backstop |
| `embedding` | `text-embedding-3-small` | pgvector ingest/search |

## Data model

- **Postgres**
  - `incidents` — every anomaly detected, with severity, score, z-score, JSON context.
  - `incident_memory` (pgvector 1536-dim) — long-term RCA memory.
  - `rca_reports` — structured RCA outputs with findings, recommendations, confidence.
  - `ops_reports` — generated shift/executive summaries.
- **Redis** — chat sessions and runtime cache.
- **NATS** — `forgemind.telemetry`, `forgemind.incidents` subjects (JetStream-ready).

## Observability

- Every FastAPI service exposes Prometheus at `/metrics`.
- Custom counters: `forgemind_anomalies_total{machine,severity}`, `forgemind_llm_tokens_total{service,tier,model,kind}`, `forgemind_llm_cost_usd{service,tier,model}`.
- The configured LLM API may return request/trace IDs; the frontend surfaces those IDs when present.
- Token and cost counters are populated from OpenAI-compatible usage metadata when available.

## Security

- JWT (HS256) auth at the API gateway; RBAC roles `viewer`, `operator`, `engineer`, `admin`.
- Rate limit at the gateway (300 req/min per IP).
- LLM API keys are stored in the shared runtime config volume when entered through the Admin Panel, and are masked in API responses.
- Per-agent keys can be rotated without rebuilding containers.
