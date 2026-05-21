# ForgeMind AI

**Autonomous Manufacturing Operations Copilot**

ForgeMind AI is an enterprise-grade industrial AI platform that continuously monitors factory telemetry, detects anomalies, predicts failures, runs autonomous root-cause investigations, and generates operational intelligence — coordinated by a multi-agent system that's transparent, observable, and production-deployable.

It is built on three core layers:

| Layer | Role |
| ---- | ---- |
| **Hermes Agent** (Nous Research) | Autonomous agents — RCA, PdM, Production Optimization, Reporting, ChatOps, Monitoring, plus a Supervisor that orchestrates them. Each agent has persistent memory, tool use, and skill reuse. |
| **LangGraph** | Deterministic stateful workflow engine. Investigation, maintenance approval, remediation, and escalation flows run as graphs whose nodes wrap Hermes agents. |
| **AI Gateway provider** | TrueFoundry AI Gateway, direct OpenAI, or any OpenAI-compatible endpoint. Providers and API keys can be set globally or per agent from the Admin Panel. |

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

Drive the end-to-end demo:

```bash
./scripts/run-demo.sh
```

This will inject six synthetic anomalies, wait for the anomaly detector to fire incidents, run the LangGraph `investigation` workflow on the first one, ask the Reporting Agent for an executive summary, and call the ChatOps Agent for a natural-language summary.

## Deploy to TrueFoundry

```bash
pip install truefoundry
export TFY_HOST=https://app.truefoundry.com
export TFY_API_KEY=tfy-pat-…
export TFY_WORKSPACE=forgemind-prod
export TFY_DOMAIN=tfy.yourcompany.com
./infra/truefoundry/deploy.sh
```

The script uploads the AI Gateway routing config, creates workspace secrets, builds + pushes 12 service images, and applies their `truefoundry.yaml` specs (autoscaling, env, health checks, observability).

## Deploy to Kubernetes (Helm)

```bash
helm upgrade --install forgemind ./infra/helm/factorymind \
  --namespace forgemind --create-namespace \
  --set secrets.tfyApiKey=<your-key> \
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
9. **AI Agent Activity** — every Hermes agent run + every LangGraph workflow run, with provider trace IDs, token usage, cost
10. **Admin Panel** — agent health checks, service readiness, per-agent provider/API key configuration
11. **Settings** — tier selection and identity

## Documentation

- [ARCHITECTURE.md](docs/ARCHITECTURE.md) — service map, data flow, integration seams
- [DEPLOYMENT.md](docs/DEPLOYMENT.md) — Docker → Kubernetes → TrueFoundry walkthrough
- [API.md](docs/API.md) — REST surface for every service
- [forgemind-ai-platform.html](docs/forgemind-ai-platform.html) - standalone HTML platform documentation with a floating table of contents
- [forgemind-ai-features-summary.html](docs/forgemind-ai-features-summary.html) - short, simple feature summary for demos and non-technical audiences
- [infra/truefoundry/README.md](infra/truefoundry/README.md) — TrueFoundry-specific notes
- [AGENTS.md](AGENTS.md) — manufacturing domain context loaded by every Hermes agent

## License

MIT.
