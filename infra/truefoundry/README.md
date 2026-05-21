# ForgeMind AI — TrueFoundry deployment

This folder contains everything TrueFoundry needs to deploy ForgeMind:

- `gateway/routing.yaml`     — AI Gateway: model tiers, fallback, cost-aware routing, semantic cache, rate limits.
- `services/*.yaml`          — Per-service `truefoundry.yaml` specs (Service kind) with autoscaling and resource limits.
- `workspace.yaml`           — Workspace + namespace bootstrap.
- `deploy.sh`                — End-to-end deploy via `tfy` CLI.

## Prerequisites

```bash
pip install truefoundry      # provides the `tfy` CLI
tfy login --host https://app.truefoundry.com
```

## Deploy

```bash
# Set creds
export TFY_HOST=https://app.truefoundry.com
export TFY_API_KEY=tfy-pat-…
export TFY_WORKSPACE=tfy-workspace-name      # e.g. forgemind-prod

# One shot:
./infra/truefoundry/deploy.sh
```

The script:
1. Validates the AI Gateway routing config and uploads it.
2. Builds and pushes container images for every service.
3. Applies each `services/<svc>.yaml` deployment spec.
4. Prints the public URLs.

## Why TrueFoundry here

TrueFoundry is the *single* enterprise AI infrastructure layer in ForgeMind:

| Layer            | Provided by TrueFoundry                                   |
| ---------------- | --------------------------------------------------------- |
| LLM Gateway      | One OpenAI-compatible endpoint over OpenAI/Anthropic/Ollama |
| Model routing    | Tier-based (fast / powerful / fallback) + cost-aware      |
| Observability    | Token usage, latency, retries, trace propagation          |
| Autoscaling      | HPA-equivalent for every Hermes / FastAPI service         |
| Deployment       | Declarative `truefoundry.yaml` per service                |
| Governance       | Workspace-level RBAC, quotas, audit logs                  |

Hermes agents route all their LLM calls through this gateway (via
`base_url` + `api_key`), so every model call is observed, cost-tracked,
and routed centrally — no provider lock-in inside the application code.
