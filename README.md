# ForgeMind AI

**Autonomous Manufacturing Operations Copilot**

ForgeMind AI is an enterprise-grade industrial AI platform that continuously monitors factory telemetry, detects anomalies, predicts failures, runs autonomous root-cause investigations, and generates operational intelligence — coordinated by a multi-agent system that's transparent, observable, and production-deployable.

It is built on three core layers:

| Layer | Role |
| ---- | ---- |
| **Hermes Agent** (Nous Research) | Autonomous agents — RCA, PdM, Production Optimization, Reporting, ChatOps, Monitoring, plus a Supervisor that orchestrates them. Each agent has persistent memory, tool use, and skill reuse. |
| **LangGraph** | Deterministic stateful workflow engine. Investigation, maintenance approval, remediation, and escalation flows run as graphs whose nodes wrap Hermes agents. |
| **Generic LLM Gateway** | Provider-agnostic OpenAI-compatible LLM layer. Works with **any** OpenAI-compatible endpoint: OpenAI, Anthropic (via proxy), Azure OpenAI, AWS Bedrock (via proxy), Google Vertex, Together, Groq, Fireworks, DeepInfra, OpenRouter, local servers (vLLM, llama.cpp, Ollama, TGI, SGLang), and **fine-tuned models** hosted on any compatible endpoint. Each agent can use a different provider, base URL, model, and API key configured via the Admin Panel or environment defaults. |

```
Telemetry → Anomaly Detection → LangGraph Investigation
                                         ↓
                                  Hermes RCA Agent
                                         ↓
                              Recommendation + Notify
                                         ↓
                              Executive Reports + ChatOps
```

## Quickstart (local, Docker Compose)

```bash
git clone <this repo> forgemind-ai
cd forgemind-ai
cp .env.example .env
# edit .env or use the Admin Panel to set an OpenAI-compatible key per agent
docker compose up --build
```

Then open:

- **Dashboard**: http://localhost:5173
- **API gateway**: http://localhost:8080
- **Grafana**: http://localhost:3000 (admin / admin)
- **Prometheus**: http://localhost:9090
- **Admin Panel**: http://localhost:5173/admin
- **LLM Gateway Admin**: http://localhost:5173/llm-admin (provider registry, model config, routing, cost tracking)

Drive the end-to-end demo:

```bash
./scripts/run-demo.sh
```

This will inject six synthetic anomalies, wait for the anomaly detector to fire incidents, run the LangGraph `investigation` workflow on the first one, ask the Reporting Agent for an executive summary, and call the ChatOps Agent for a natural-language summary.

## Bring Your Own Model

ForgeMind's LLM layer is a **generic OpenAI-compatible gateway**. You can plug in any provider or fine-tuned model by serving it behind an OpenAI-compatible API and configuring the base URL + model + API key.

### Fine-tuned model example

1. **Serve your fine-tuned model** behind an OpenAI-compatible endpoint:
   - **vLLM**: `vllm serve <your-model> --api-key <key>`
   - **llama.cpp**: `./server -m model.gguf --port 8080`
   - **TGI** (HuggingFace): `text-generation-launcher --model-id <your-model>`
   - **Ollama**: `ollama serve` (defaults to `http://localhost:11434`)

2. **Configure in the Admin Panel**:
   - Open http://localhost:5173/admin
   - Set the **base URL** (e.g., `http://localhost:8000/v1` for vLLM, `http://localhost:11434/v1` for Ollama)
   - Set the **model** name (e.g., `my-fine-tuned-hermes-3`, or `llama3.2:3b` for Ollama)
   - Set the **API key** if required by your server
   - Click **Update Default Config** to apply globally, or configure per-agent for specialist routing (e.g., RCA Agent uses your fine-tuned model, ChatOps uses OpenAI GPT-4o)

3. **Per-agent overrides**: Each agent (RCA, PdM, ChatOps, Reporting, Production Optimization, Monitoring, Supervisor) can have its own provider, base URL, model, and API key. This lets you:
   - Route critical reasoning (RCA, PdM) to a fine-tuned industrial model
   - Route fast classification (Monitoring, Remediation) to a cheaper/faster provider
   - Keep ChatOps on a hosted model with long context support
   - Mix local (Ollama/vLLM), hosted (OpenAI/Anthropic/Together), and fine-tuned models in one deployment

### Supported providers (examples)

All providers that expose an OpenAI-compatible `/v1/chat/completions` endpoint:

- **OpenAI**: `base_url=https://api.openai.com/v1`, `model=gpt-4o`
- **Anthropic** (via LiteLLM/OpenRouter): `base_url=https://openrouter.ai/api/v1`, `model=anthropic/claude-sonnet-4`
- **Azure OpenAI**: `base_url=https://<resource>.openai.azure.com/openai/deployments/<deployment>`, `model=<deployment-name>`
- **AWS Bedrock** (via LiteLLM proxy): `base_url=http://litellm:8000/v1`, `model=bedrock/anthropic.claude-3-sonnet`
- **Google Vertex** (via LiteLLM proxy): `base_url=http://litellm:8000/v1`, `model=vertex_ai/gemini-2.0-flash-exp`
- **Together**: `base_url=https://api.together.xyz/v1`, `model=mistralai/Mixtral-8x7B-Instruct-v0.1`
- **Groq**: `base_url=https://api.groq.com/openai/v1`, `model=llama-3.3-70b-versatile`
- **Fireworks**: `base_url=https://api.fireworks.ai/inference/v1`, `model=accounts/fireworks/models/llama-v3p1-70b-instruct`
- **DeepInfra**: `base_url=https://api.deepinfra.com/v1/openai`, `model=meta-llama/Meta-Llama-3.1-70B-Instruct`
- **OpenRouter**: `base_url=https://openrouter.ai/api/v1`, `model=<any-model-on-openrouter>`
- **vLLM** (local/remote): `base_url=http://localhost:8000/v1`, `model=<your-model-name>`
- **llama.cpp** (local): `base_url=http://localhost:8080/v1`, `model=<model-name>`
- **Ollama** (local): `base_url=http://localhost:11434/v1`, `model=llama3.2:3b`
- **TGI** (HuggingFace): `base_url=http://localhost:8080/v1`, `model=<model-id>`
- **SGLang** (local/remote): `base_url=http://localhost:30000/v1`, `model=<model-path>`

If a provider requires a proxy to expose the OpenAI-compatible format (e.g., AWS Bedrock, Google Vertex without native support), use [LiteLLM](https://github.com/BerriAI/litellm) or similar.

## Deploy to Kubernetes (Helm)

```bash
helm upgrade --install forgemind ./infra/helm/factorymind \
  --namespace forgemind --create-namespace \
  --set config.llm.baseUrl=https://api.openai.com/v1 \
  --set secrets.llmApiKey=<your-key> \
  --set secrets.jwtSecret=<random-string>
```

## Architecture at a glance

12 microservices (Python FastAPI), one Vue 3 + Tailwind SPA, plus Postgres+pgvector / Redis / NATS / Prometheus / Grafana.

| Service                | Purpose                                                                    |
| ---------------------- | -------------------------------------------------------------------------- |
| `api-gateway`          | JWT auth, rate limiting, reverse proxy to downstream services              |
| `telemetry-simulator`  | 10 virtual machines (CNC/PRESS/ROBOT/OVEN/CONVEYOR/INSPECTION) streaming telemetry to NATS, with injectable anomalies |
| `telemetry-ingestion`  | HTTP ingestion seam for real plant gateways (PLC / OPC-UA)                 |
| `anomaly-detection`    | Statistical (z-score + EWMA + IQR) + Isolation Forest detectors, LLM-assisted severity classification (FAST tier) |
| `rca-service`          | **Hermes RCA Agent** — pgvector similarity over past incidents, structured RCA reports |
| `predictive-maintenance` | Risk-decayed failure forecasting + Hermes PdM agent explanations         |
| `ai-orchestrator`      | **Hermes Supervisor** — routes between Monitoring / PdM / Optimization / Reporting / RCA |
| `workflow-engine`      | **LangGraph** — `investigation`, `maintenance_approval`, `remediation`, `escalation` graphs |
| `chatops-service`      | **Hermes ChatOps Agent** with SSE streaming                                |
| `reporting-service`    | Hermes Reporting Agent — shift summaries, executive reports                |
| `notification-service` | Subscribes to incidents, adaptive flood suppression, fan-out               |
| `frontend`             | Vue 3 + Tailwind, 10 pages, live charts, dark Datadog-style UI             |

## The frontend

1. **Operations Dashboard** — totals, top failure risks, live vibration chart, incident feed
2. **Machine Health** — per-machine cards, live readings, anomaly injectors
3. **Incident Explorer** — filterable incident list, one-click Run RCA
4. **Predictive Maintenance** — risk 24h/72h, ETA, recommended maintenance windows
5. **Production Analytics** — throughput, defects, per-line view
6. **AI RCA Reports** — full RCA report viewer with findings + recommendations
7. **ChatOps Console** — tool-using Hermes agent with preset prompts
8. **Executive Reports** — generated shift / executive summaries
9. **AI Agent Activity** — every Hermes agent run + every LangGraph workflow run, with LLM trace IDs, token usage, cost
10. **Admin Panel** — agent health checks, service readiness, per-agent API base URL/model/key configuration, **user management** (bcrypt-hashed credentials, add/edit/delete users, role assignment)
11. **Settings** — tier selection and identity

## Authentication

Users live in a small persistent store (`auth_users.json` on the
`agent-config` volume, bcrypt-hashed). The store is administered from
the Admin Panel's **Users** section or via the admin API:

```
GET    /api/v1/admin/auth/users               # list
PUT    /api/v1/admin/auth/users/<username>    # upsert: {role, password?}
DELETE /api/v1/admin/auth/users/<username>    # delete
```

A fresh stack is bootstrapped from env vars (`AUTH_ADMIN_USER` /
`AUTH_ADMIN_PASS`, etc. — see `.env.example`). As soon as an admin
edits or adds a user from the panel, the store entry takes precedence
over the env vars for that username. This keeps zero-config dev easy
while letting production deployments rotate passwords without env-var
changes / container restarts.

## Testing

The repository ships with a comprehensive end-to-end test suite under `tests/e2e/`
that runs every service in-process — no Docker, no Postgres, no NATS, no real LLM
provider required. **289 tests, 96% line coverage.**

### Install test dependencies

```bash
pip install fastapi==0.110.0 'uvicorn[standard]==0.27.1' httpx==0.27.0 \
  pydantic==2.6.4 pydantic-settings==2.2.1 structlog==24.1.0 \
  prometheus-client==0.20.0 nats-py==2.7.2 'sqlalchemy[asyncio]==2.0.29' \
  aiosqlite numpy==1.26.4 'python-jose[cryptography]==3.3.0' \
  cryptography==42.0.2 pgvector==0.2.5 python-multipart==0.0.6 \
  scikit-learn==1.4.1.post1 asyncpg==0.29.0 langgraph \
  pytest pytest-asyncio pytest-cov
```

### Run the suite

```bash
# All E2E tests (≈20s)
python3 -m pytest tests/e2e/

# With coverage (needs the .coveragerc in repo root for thread tracing)
python3 -m pytest tests/e2e/ \
  --cov=shared/forgemind_common --cov=services \
  --cov-config=.coveragerc --cov-report=term-missing
```

What gets tested:

- **Per-service contracts** — health, CRUD, auth, validation for each of the 12 services
- **Cross-service flows** — telemetry → anomaly → incident → investigation workflow → RCA → reporting → ChatOps, end-to-end through the API gateway
- **LLM Gateway** — provider/model CRUD, agent routing, fallback chains, quotas, audit logging, three provider translators (OpenAI / Anthropic / Gemini)
- **Shared library** — config, auth, messaging, LLM client, gateway, Hermes runtime, runtime config

See [`tests/e2e/README.md`](tests/e2e/README.md) for the harness architecture
(in-memory NATS broker, SQLite-backed Postgres replacement, mocked LLM gateway,
ASGI routing transport that wires the services together).

## Documentation

- [ARCHITECTURE.md](docs/ARCHITECTURE.md) — service map, data flow, integration seams
- [DEPLOYMENT.md](docs/DEPLOYMENT.md) — Docker and Kubernetes walkthrough
- [API.md](docs/API.md) — REST surface for every service
- [LLM_GATEWAY_API.md](docs/LLM_GATEWAY_API.md) — full LLM Gateway admin + inference API
- [tests/e2e/README.md](tests/e2e/README.md) — end-to-end test harness architecture
- [forgemind-ai-platform.html](docs/forgemind-ai-platform.html) - standalone HTML platform documentation with a floating table of contents
- [forgemind-ai-features-summary.html](docs/forgemind-ai-features-summary.html) - short, simple feature summary for demos and non-technical audiences
- [AGENTS.md](AGENTS.md) — manufacturing domain context loaded by every Hermes agent

## License

MIT.
