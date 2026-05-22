# Deployment Guide

Three deployment targets, in increasing order of seriousness.

## 1. Local development (Docker Compose)

```bash
cp .env.example .env
# Set OPENAI_API_KEY and OPENAI_BASE_URL (defaults to https://api.openai.com/v1),
# or configure per-agent via the Admin Panel at http://localhost:5173/admin.
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

## 3. LLM Gateway Configuration

ForgeMind's LLM layer is a **generic OpenAI-compatible gateway**. Every Hermes agent
routes through a configured endpoint with per-agent overrides:

```python
_HermesAIAgent(
    model=runtime_config.model_for(tier),
    base_url=runtime_config.openai_base_url(),
    api_key=runtime_config.api_key,
    ...
)
```

Configuration is hierarchical (later sources override earlier):

1. **Environment defaults**: `OPENAI_BASE_URL`, `OPENAI_API_KEY`, `OPENAI_MODEL_FAST`, `OPENAI_MODEL_POWERFUL`
2. **Global runtime config**: Set via Admin Panel, applies to all agents
3. **Per-agent runtime config**: Set via Admin Panel, overrides global for that agent

The Admin Panel (`/admin`) writes per-agent provider, model, base URL, and API key
to a shared runtime config volume (`/app/data/agent-config.json` inside containers).
Services re-read this file on every agent run, so switching providers or rotating
keys does not require rebuilding containers.

### Bring Your Own Model

You can plug in **any** OpenAI-compatible provider or fine-tuned model:

#### Example 1: Local vLLM with a fine-tuned model

```bash
# Serve your fine-tuned model locally
vllm serve my-fine-tuned-hermes-3 --api-key my-secret-key --port 8000
```

Then in the Admin Panel:
- **Base URL**: `http://host.docker.internal:8000/v1` (Docker Compose on macOS/Windows) or `http://<host-ip>:8000/v1` (Linux/K8s)
- **Model**: `my-fine-tuned-hermes-3`
- **API Key**: `my-secret-key`
- **Enabled**: `true`

Apply globally or per-agent (e.g., RCA Agent only).

#### Example 2: Ollama for fast local inference

```bash
# Serve Ollama locally
ollama serve  # defaults to http://localhost:11434
ollama pull llama3.2:3b
```

Then in the Admin Panel (for the Monitoring Agent):
- **Base URL**: `http://host.docker.internal:11434/v1`
- **Model**: `llama3.2:3b`
- **API Key**: (leave blank, Ollama doesn't require it)
- **Enabled**: `true`

#### Example 3: Azure OpenAI for compliance

In the Admin Panel:
- **Base URL**: `https://<resource>.openai.azure.com/openai/deployments/<deployment-name>`
- **Model**: `<deployment-name>`
- **API Key**: `<your-azure-key>`
- **Enabled**: `true`

#### Example 4: Mix providers per agent

Set global defaults to OpenAI, then override:
- **RCA Agent**: vLLM with fine-tuned industrial model at `http://vllm:8000/v1`
- **Monitoring Agent**: local Ollama at `http://ollama:11434/v1`
- **ChatOps Agent**: OpenAI GPT-4o (uses global defaults)
- **PdM Agent**: Together API at `https://api.together.xyz/v1` with `mistralai/Mixtral-8x7B-Instruct-v0.1`

### Supported providers

All providers that expose an OpenAI-compatible `/v1/chat/completions` endpoint:

- **OpenAI**: `https://api.openai.com/v1`
- **Anthropic** (via proxy): Use LiteLLM or OpenRouter
- **Azure OpenAI**: `https://<resource>.openai.azure.com/openai/deployments/<deployment>`
- **AWS Bedrock** (via proxy): Use LiteLLM proxy
- **Google Vertex** (via proxy): Use LiteLLM proxy
- **Together**: `https://api.together.xyz/v1`
- **Groq**: `https://api.groq.com/openai/v1`
- **Fireworks**: `https://api.fireworks.ai/inference/v1`
- **DeepInfra**: `https://api.deepinfra.com/v1/openai`
- **OpenRouter**: `https://openrouter.ai/api/v1`
- **vLLM** (local/remote): `http://localhost:8000/v1`
- **llama.cpp** (local): `http://localhost:8080/v1`
- **Ollama** (local): `http://localhost:11434/v1`
- **TGI** (HuggingFace): `http://localhost:8080/v1`
- **SGLang** (local/remote): `http://localhost:30000/v1`

If a provider doesn't natively support OpenAI format, use [LiteLLM](https://github.com/BerriAI/litellm) as a proxy.

### LLM Gateway Service Configuration

The centralized LLM Gateway service (`llm-gateway`) requires the following environment variable:

```bash
GATEWAY_SECRET_KEY=<32-byte-hex-key>  # For encrypting provider API keys at rest
```

Generate a secure key:

```bash
openssl rand -hex 32
```

In `docker-compose.yml`, this is automatically set. For Kubernetes, add to your Helm values or Secret:

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: llm-gateway-secrets
type: Opaque
stringData:
  GATEWAY_SECRET_KEY: "<your-32-byte-hex-key>"
```

**Admin Panel Access**: Navigate to `/llm-admin` to:
- Register LLM providers (cloud or self-hosted)
- Define models with cost/token limits
- Configure per-agent routing and fallback chains
- Monitor usage, cost, and provider health
- View audit logs of all inference calls

All provider API keys are encrypted using Fernet before storage. The gateway decrypts them on-demand when routing requests.

### Running a Local Ollama/vLLM and Registering It

**Ollama (lightweight, CPU/GPU)**:

```bash
# Install Ollama
curl -fsSL https://ollama.com/install.sh | sh

# Start the server
ollama serve  # listens on http://localhost:11434

# Pull a model
ollama pull llama3.2:3b
```

Then in the Admin Panel (`/llm-admin`):
1. Click "Add Provider"
2. Name: "Local Ollama"
3. Kind: Self-Hosted
4. Provider Type: `ollama`
5. Base URL: `http://host.docker.internal:11434/v1` (Docker Compose) or `http://ollama:11434/v1` (K8s with service)
6. API Key: (leave blank)
7. Enabled: `true`
8. Click "Save"
9. Click "Add Model" and select the Ollama provider, set model name to `llama3.2:3b`

**vLLM (high-performance, GPU-optimized)**:

```bash
# Install vLLM
pip install vllm

# Serve a model
vllm serve meta-llama/Llama-3.2-3B-Instruct --api-key my-secret-key --port 8000
```

Then in the Admin Panel:
1. Click "Add Provider"
2. Name: "Local vLLM"
3. Kind: Self-Hosted
4. Provider Type: `vllm`
5. Base URL: `http://host.docker.internal:8000/v1`
6. API Key: `my-secret-key`
7. Enabled: `true`
8. Click "Save"
9. Click "Add Model", select the vLLM provider, set model name to `meta-llama/Llama-3.2-3B-Instruct`

Once registered, assign the model to an agent via "Agent Routing" in the admin panel.

### Rolling updates

**LLM config changes** (provider, model, base URL, API key) via the Admin Panel take
effect immediately on the next agent run. No restart required.

**Code changes** require rebuilding affected services:

```bash
docker compose up -d --build api-gateway ai-orchestrator rca-service chatops-service workflow-engine
```

### User authentication

ForgeMind ships with a persistent, bcrypt-hashed user store managed from the
Admin Panel (**Admin → Users** section) and the matching admin API:

```
GET    /api/v1/admin/auth/users
PUT    /api/v1/admin/auth/users/<username>     # { "role": "...", "password": "..." }
DELETE /api/v1/admin/auth/users/<username>
```

The store file (`auth_users.json`) lives on the `agent-config` volume next to
`agent_config.json`. Mode 0600.

`AUTH_*_USER` / `AUTH_*_PASS` env vars (see `.env.example`) are **bootstrap
credentials only** — they let a fresh stack log in without any setup. As soon
as you add or override a user from the Admin Panel, the store takes precedence
over the env-var version of that username. Workflow:

1. `docker compose up` — log in with the env-var admin (`admin` / `admin` in
   the shipped defaults; change them in `.env`).
2. Open **Admin → Users**. Click "Move to store" on the bootstrap admin and
   set a strong password. The env-var version becomes inert for that name.
3. Add additional users from the panel.
4. Delete the env-var defaults from your `.env` or Kubernetes secret once
   everyone you need is in the store.

In Kubernetes, set the bootstrap creds via the `forgemind-secrets` Secret or
inject them through your existing secret manager (external-secrets, Vault
agent, etc.). Once users are seeded via the panel, the secret can be reduced
to just `JWT_SECRET` + `POSTGRES_PASSWORD`.

### Observability dashboards

Every service exposes `/metrics` for Prometheus. LLM token and cost counters are
reported by service, tier, model, and kind when the configured API returns usage
metadata.
