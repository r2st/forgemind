# Deployment Guide

Three deployment targets, in increasing order of seriousness.

## 1. Local development (Docker Compose)

```bash
cp .env.example .env
# Required: TFY_GATEWAY_API_KEY=<your-truefoundry-pat>
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
  --set secrets.tfyApiKey=<your-truefoundry-pat> \
  --set secrets.jwtSecret=$(openssl rand -hex 32) \
  --set ingress.host=forgemind.example.com
```

Each service gets a Deployment, Service, and (for hot services) HPA. Resource requests are tuned per-service in `values.yaml`. Infrastructure (Postgres + pgvector, Redis, NATS) can be turned off via `--set infra.postgres.enabled=false` etc. when using managed services.

## 3. TrueFoundry (recommended for production)

Why TrueFoundry: because the same platform that serves your LLMs through the AI Gateway can run the services that *call* the AI Gateway. Trace IDs propagate; cost accounting is unified; quotas are enforced at one boundary.

```bash
pip install truefoundry
tfy login --host https://app.truefoundry.com

export TFY_HOST=https://app.truefoundry.com
export TFY_API_KEY=tfy-pat-…
export TFY_WORKSPACE=forgemind-prod
export TFY_DOMAIN=tfy.yourcompany.com

# Optional — providers will be created from these
export OPENAI_API_KEY=sk-…
export ANTHROPIC_API_KEY=sk-ant-…

./infra/truefoundry/deploy.sh
```

The script:

1. Applies `workspace.yaml` (creates the workspace if missing, sets resource quota).
2. Uploads `gateway/routing.yaml` (defines `fast` / `powerful` / `fallback` / `embedding` tiers with multi-provider fallback, cost caps, semantic cache, per-service quotas).
3. Creates workspace secrets: `tfy-gateway-key`, `jwt-secret`, `openai-api-key`, `anthropic-api-key`.
4. Applies all 12 service specs (`infra/truefoundry/services/*.yaml`). Each spec is a `tfy.Service` with image build, autoscaling (CPU + RPS), env (env vars sourced from `tfy-secret://` paths), health checks, OTel + Prom + log collection.
5. Prints the public URL per service.

### How Hermes routes through TrueFoundry

Every Hermes agent in ForgeMind is constructed with:

```python
_HermesAIAgent(
    model=settings.tfy_model_powerful,    # logical model name; gateway routes
    base_url=f"{settings.tfy_gateway_base_url}/api/inference/openai",
    api_key=settings.tfy_gateway_api_key,
    ...
)
```

That means Hermes treats TrueFoundry as a plain OpenAI-compatible endpoint. Provider abstraction, fallback, observability, and rate limiting all happen inside the gateway — Hermes does not need to know about Anthropic, Ollama, or any specific provider. The application is provider-agnostic by construction.

### Rolling updates

Each `tfy apply` is idempotent. Image changes trigger a rolling restart; env-only changes do a hot reload where supported. To roll back:

```bash
tfy services rollback <svc> --workspace $TFY_WORKSPACE
```

### Observability dashboards

After deploy, the gateway exposes per-model dashboards in the TrueFoundry UI: token volume, latency p50/p95/p99, fallback rate, cache hit rate, cost per agent. Application metrics from the FastAPI services are scraped by TrueFoundry's Prometheus and surfaced in the same workspace.
