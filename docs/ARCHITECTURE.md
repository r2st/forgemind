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
│               Generic OpenAI-Compatible LLM Gateway                  │
│   Provider-agnostic: OpenAI, Anthropic, Azure, Bedrock, Vertex,     │
│   Together, Groq, Fireworks, DeepInfra, OpenRouter, vLLM, llama.cpp,│
│   Ollama, TGI, SGLang, or any fine-tuned model on a compatible API  │
│   Configured per-agent: base_url · model · api_key · enabled        │
└──────────────────────────────────────────────────────────────────────┘
```

Hermes routes every LLM call through the configured OpenAI-compatible API
(`base_url` + `api_key` + `model`). LangGraph calls Hermes agents as nodes. The
Admin Panel can override base URL, model, API key, and enabled state **per agent**
or set global defaults. This lets each agent use a different provider or model:
e.g., RCA Agent on a fine-tuned industrial model, ChatOps on OpenAI GPT-4o,
Monitoring on a fast local Ollama instance.

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
                       │  Generic OpenAI-Compatible LLM Gateway               │
                       │  Provider-agnostic: OpenAI, Anthropic, Azure,        │
                       │  Bedrock, Vertex, Together, Groq, Fireworks,         │
                       │  DeepInfra, OpenRouter, vLLM, llama.cpp, Ollama,     │
                       │  TGI, SGLang, fine-tuned models, or any compatible   │
                       │  endpoint. Per-agent base_url/model/api_key config.  │
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

## LLM Gateway Architecture

The LLM layer is a **centralized Generic Enterprise LLM Gateway** service (`llm-gateway`) that
provides a unified control plane for all AI inference. All Hermes agents call the gateway's
OpenAI-compatible `/v1/chat/completions` endpoint; the gateway handles routing, translation,
fallback, observability, and cost tracking.

### Architecture flow

```
Hermes Agents (RCA, PdM, ChatOps, etc.)
    │ LLMClient("agent-name")
    │ POST /v1/chat/completions
    │ X-Agent: agent-name
    ▼
┌─────────────────────────────────────────────────────────────┐
│ LLM Gateway (llm-gateway:8000)                              │
│ ┌─────────────┐   ┌──────────────┐   ┌─────────────────┐   │
│ │ Provider    │   │ Model        │   │ Agent → Model   │   │
│ │ Registry    │ → │ Registry     │ → │ Mapping         │   │
│ └─────────────┘   └──────────────┘   └─────────────────┘   │
│         │                                     │             │
│         ▼                                     ▼             │
│ ┌──────────────────────────────────────────────────────┐   │
│ │ Routing Engine (cheapest / lowest_latency /          │   │
│ │                 highest_quality / local_only ...)    │   │
│ └──────────────────────────────────────────────────────┘   │
│         │                                                   │
│         ▼                                                   │
│ ┌──────────────────────────────────────────────────────┐   │
│ │ Translation Layer                                     │   │
│ │ • OpenAI → pass through                              │   │
│ │ • Anthropic → convert to Messages API                │   │
│ │ • Gemini → convert to Gemini format                  │   │
│ │ • Bedrock → AWS SDK call                             │   │
│ │ • vLLM/Ollama/TGI/OpenRouter → pass through          │   │
│ └──────────────────────────────────────────────────────┘   │
│         │                                                   │
│         ▼                                                   │
│ ┌──────────────────────────────────────────────────────┐   │
│ │ Fallback Chain Executor                               │   │
│ │ primary → fallback[0] → fallback[1] → ... → error    │   │
│ └──────────────────────────────────────────────────────┘   │
│         │                                                   │
│         ▼                                                   │
│ ┌──────────────────────────────────────────────────────┐   │
│ │ Observability & Governance                            │   │
│ │ • Prometheus metrics (tokens, cost, latency, errors)  │   │
│ │ • Audit log (every inference call)                    │   │
│ │ • Per-agent quotas & rate limits                      │   │
│ │ • Encrypted credential storage (Fernet)               │   │
│ └──────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
    │
    ▼
Cloud/Self-Hosted Providers (OpenAI, Anthropic, Gemini,
Azure, Bedrock, Groq, Together, OpenRouter, Ollama, vLLM, ...)
```

### Key features

**Provider Registry**: Register multiple LLM providers (cloud or self-hosted) with encrypted credentials.

**Model Registry**: Define models per provider with cost/token limits, context windows, and capabilities.

**Per-Agent Routing**: Each agent (Monitoring, RCA, PdM, ChatOps, etc.) has its own primary model and fallback chain.

**Routing Strategies**: `cheapest`, `lowest_latency`, `highest_quality`, `local_only`, `gpu_aware`, `compliance_aware`.

**Automatic Fallback**: On error/timeout/rate-limit, walk the fallback chain. Every fallback event is logged.

**Cost Tracking**: Real-time per-agent, per-model, per-provider cost accumulation.

**Admin Panel**: CRUD for providers, models, agent routing, fallback config, usage analytics, health dashboard.

### Supported providers

| Provider | Type | Translation |
| -------- | ---- | ----------- |
| OpenAI | Cloud | Pass-through |
| Anthropic | Cloud | Messages API |
| Google Gemini | Cloud | Gemini API |
| Azure OpenAI | Cloud | Pass-through |
| AWS Bedrock | Cloud | Bedrock SDK |
| OpenRouter | Cloud | Pass-through |
| Groq | Cloud | Pass-through |
| Together AI | Cloud | Pass-through |
| Ollama | Self-Hosted | Pass-through |
| vLLM | Self-Hosted | Pass-through |
| TGI (Text Generation Inference) | Self-Hosted | Pass-through |
| llama.cpp | Self-Hosted | Pass-through |
| Custom OpenAI-Compatible | Any | Pass-through |

### Configuration hierarchy

1. **Provider registry** (Admin Panel) — define cloud/self-hosted providers with credentials
2. **Model registry** (Admin Panel) — define models per provider with cost/limits
3. **Agent routing** (Admin Panel) — assign primary + fallback models per agent
4. **Routing policy** (Admin Panel) — global or per-agent routing strategy

This lets you:
- Route RCA and PdM to a fine-tuned industrial model (e.g., served by vLLM)
- Route Monitoring to a fast local Ollama instance
- Keep ChatOps on OpenAI GPT-4o for long context
- Use Azure OpenAI for compliance-sensitive workloads
- Automatically fail over to a cloud provider if local models are down

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
