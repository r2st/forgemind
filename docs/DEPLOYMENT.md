# Deployment Guide

Three deployment targets, in increasing order of seriousness.

## 1. Local development (Docker Compose)

```bash
cp .env.example .env
# Set OPENAI_API_KEY, or configure keys in /admin.
docker compose up --build
```

Bring-up takes ~3 minutes the first time (most of it is `pip install` for the RCA/orchestrator/chatops/workflow-engine containers that pull `hermes-agent` + `langgraph`). Subsequent rebuilds are sub-30s thanks to layer caching.

Useful targets:

```bash
# Tail one service
docker compose logs -f anomaly-detection

# Reset everything
docker compose down -v

# Open Postgres
docker compose exec postgres psql -U forgemind

# Drive the demo end-to-end
./scripts/run-demo.sh
```

## 2. Kubernetes (Helm)

The Helm chart is in `infra/helm/factorymind/` (folder name kept stable; chart `name` is `forgemind`).

```bash
helm dep update infra/helm/factorymind
helm install forgemind infra/helm/factorymind \
  --namespace forgemind --create-namespace \
  --set config.llm.baseUrl=https://api.openai.com/v1 \
  --set secrets.llmApiKey=<your-openai-compatible-key> \
  --set secrets.jwtSecret=$(openssl rand -hex 32) \
  --set ingress.host=forgemind.example.com
```

Each service gets a Deployment, Service, and (for hot services) HPA. Resource requests are tuned per-service in `values.yaml`. Infrastructure (Postgres + pgvector, Redis, NATS) can be turned off via `--set infra.postgres.enabled=false` etc. when using managed services.

## 3. How Hermes routes through the configured API

Every Hermes agent in ForgeMind is constructed with:

```python
_HermesAIAgent(
    model=runtime_config.model_for(tier),
    base_url=runtime_config.openai_base_url(),
    api_key=runtime_config.api_key,
    ...
)
```

The Admin Panel writes per-agent API type, model, base URL, and API key
overrides to the shared runtime config volume. Without an override, agents use
`LLM_PROVIDER=openai-compatible` and the `OPENAI_*` environment defaults.

### Rolling updates

For Compose, rebuild and recreate the affected services:

```bash
docker compose up -d --build api-gateway ai-orchestrator rca-service chatops-service workflow-engine
```

### Observability dashboards

Every service exposes `/metrics` for Prometheus. LLM token and cost counters are
reported by service, tier, model, and kind when the configured API returns usage
metadata.
