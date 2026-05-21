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
│                          TrueFoundry                                 │
│   AI Gateway (multi-model routing, fallback, cost cap, cache)        │
│   Model serving · Autoscaling · Observability · Governance · Deploy  │
└──────────────────────────────────────────────────────────────────────┘
```

Hermes routes every LLM call through TrueFoundry (`base_url` + `api_key`). LangGraph calls Hermes agents as nodes. Nothing in the application talks to OpenAI/Anthropic/Ollama directly — that lock-in is owned by the gateway.

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
                       │  TrueFoundry AI Gateway                              │
                       │  (OpenAI/Anthropic/Ollama, tier routing, cost cap,   │
                       │   semantic cache, observability)                     │
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

## TrueFoundry AI Gateway tiers

Hermes asks for a *tier*; the gateway picks a concrete model.

| Tier | Primary | Fallbacks | Cost cap / req | Used by |
| ---- | ------- | --------- | -------------- | ------- |
| `fast` | `openai-main/gpt-4o-mini` | `anthropic-main/claude-haiku-4-5`, `ollama-local/llama3.1:8b` | $0.01 | severity classifier, remediation agent, monitoring agent |
| `powerful` | `anthropic-main/claude-sonnet-4-5` | `openai-main/gpt-4o`, `ollama-local/llama3.1:70b` | $0.50 | RCA, PdM, supervisor, reporting, chatops |
| `fallback` | `ollama-local/llama3.1:8b` | — | $0 | last-resort backstop |
| `embedding` | `openai-main/text-embedding-3-small` | `ollama-local/nomic-embed-text` | — | pgvector ingest/search |

Routing rules live in `infra/truefoundry/gateway/routing.yaml`.

## Data model

- **Postgres**
  - `incidents` — every anomaly detected, with severity, score, z-score, JSON context.
  - `incident_memory` (pgvector 1536-dim) — long-term RCA memory.
  - `rca_reports` — structured RCA outputs with findings, recommendations, confidence.
  - `ops_reports` — generated shift/executive summaries.
- **Redis** — chat sessions, semantic cache (passthrough via gateway).
- **NATS** — `forgemind.telemetry`, `forgemind.incidents` subjects (JetStream-ready).

## Observability

- Every FastAPI service exposes Prometheus at `/metrics`.
- Custom counters: `forgemind_anomalies_total{machine,severity}`, `forgemind_llm_tokens_total{service,tier,model,kind}`, `forgemind_llm_cost_usd{service,tier,model}`.
- TrueFoundry adds inference-side metrics: per-model latency, retries, fallbacks, cache hit rate.
- Frontend AI Agent Activity page surfaces TrueFoundry trace IDs so an operator can pivot from a UI row to a gateway trace.

## Security

- JWT (HS256) auth at the API gateway; RBAC roles `viewer`, `operator`, `engineer`, `admin`.
- Rate limit at the gateway (300 req/min per IP).
- All TrueFoundry secrets stored in `tfy-secret://` paths, not env vars in the image.
- Per-service quotas in the gateway config (daily tokens and cost cap per service).
