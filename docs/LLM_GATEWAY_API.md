# LLM Gateway Admin API Reference

The LLM Gateway provides a comprehensive admin API for managing providers, models, and agent routing configuration.

## Provider Management

### List Providers
```
GET /admin/llm/providers
```

### Create Provider
```
POST /admin/llm/providers
Content-Type: application/json

{
  "name": "My vLLM Server",
  "kind": "self_hosted",
  "provider_type": "vllm",
  "base_url": "http://vllm:8000/v1",
  "api_key": "secret-key",
  "auth_header": "Authorization",
  "enabled": true,
  "metadata": {}
}
```

### Update Provider
```
PUT /admin/llm/providers/{id}
Content-Type: application/json

{
  "name": "Updated Provider Name",
  "enabled": false
}
```

### Delete Provider
```
DELETE /admin/llm/providers/{id}
```

## Model Registry

### List Models
```
GET /admin/llm/models
```

### Create Model
```
POST /admin/llm/models
Content-Type: application/json

{
  "provider_id": "provider-uuid",
  "model_name": "llama-3-70b-instruct",
  "display_name": "Llama 3 70B Instruct",
  "context_window": 8192,
  "max_output": 4096,
  "cost_per_input_tok": 0.0005,
  "cost_per_output_tok": 0.0015,
  "capabilities": ["reasoning", "tools"],
  "enabled": true
}
```

### Update Model
```
PUT /admin/llm/models/{id}
Content-Type: application/json

{
  "enabled": false,
  "cost_per_input_tok": 0.0006
}
```

### Delete Model
```
DELETE /admin/llm/models/{id}
```

## Agent Routing Configuration

### Get Agent Routing
```
GET /admin/llm/agents/{agent_name}/routing
```

### Update Agent Routing
```
PUT /admin/llm/agents/{agent_name}/routing
Content-Type: application/json

{
  "primary_model_id": "model-uuid",
  "routing_strategy": "highest_quality",
  "temperature": 0.7,
  "max_tokens": 4096,
  "reasoning_mode": true,
  "timeout_s": 120,
  "retry_policy": {
    "max_retries": 3,
    "backoff_factor": 2
  }
}
```

**Routing Strategies:**
- `cheapest` - Route to the lowest-cost model
- `lowest_latency` - Route to the fastest-responding model
- `highest_quality` - Route to the most capable model
- `local_only` - Only use self-hosted models
- `gpu_aware` - Consider GPU availability
- `compliance_aware` - Respect data sovereignty rules

## Fallback Configuration

### Get Fallback Chain
```
GET /admin/llm/agents/{agent_name}/fallback
```

### Update Fallback Chain
```
PUT /admin/llm/agents/{agent_name}/fallback
Content-Type: application/json

{
  "fallback_model_ids": ["model-uuid-1", "model-uuid-2", "model-uuid-3"]
}
```

The gateway will attempt models in order until one succeeds. All fallback events are logged.

## Usage Analytics

### Get Usage Stats
```
GET /admin/llm/usage?agent=rca-agent&model=llama-3-70b&provider=vllm-prod&window=7d
```

**Query Parameters:**
- `agent` - Filter by agent name
- `model` - Filter by model name
- `provider` - Filter by provider name
- `window` - Time window (1h, 24h, 7d, 30d)

**Response:**
```json
{
  "usage": [
    {
      "agent": "rca-agent",
      "model": "llama-3-70b-instruct",
      "provider": "vllm-prod",
      "requests": 1250,
      "input_tokens": 3500000,
      "output_tokens": 850000,
      "errors": 5,
      "avg_latency_ms": 450
    }
  ]
}
```

## Cost Monitoring

### Get Cost Breakdown
```
GET /admin/llm/cost?window=month
```

**Query Parameters:**
- `window` - One of: `day`, `week`, `month`

**Response:**
```json
{
  "today": 12.45,
  "week": 87.32,
  "month": 342.18,
  "by_agent": {
    "rca-agent": 120.50,
    "chatops-agent": 95.30,
    "pdm-agent": 68.40
  },
  "by_provider": {
    "openai": 200.15,
    "vllm-prod": 84.05
  },
  "by_model": {
    "gpt-4o": 150.20,
    "llama-3-70b": 84.05,
    "gpt-4o-mini": 50.00
  }
}
```

## Provider Health

### Get Provider Health Status
```
GET /admin/llm/health
```

**Response:**
```json
{
  "providers": [
    {
      "provider_id": "provider-uuid",
      "provider_name": "OpenAI Production",
      "status": "healthy",
      "latency_ms": 280,
      "last_check": "2025-01-15T14:30:00Z",
      "error_rate": 0.002,
      "models_available": 5
    },
    {
      "provider_id": "provider-uuid-2",
      "provider_name": "Local vLLM",
      "status": "degraded",
      "latency_ms": 1200,
      "last_check": "2025-01-15T14:29:55Z",
      "error_rate": 0.15,
      "models_available": 2
    }
  ]
}
```

**Health Status Values:**
- `healthy` - Provider responding normally
- `degraded` - High latency or error rate
- `unhealthy` - Provider unreachable or failing

## Audit Log

### Get Audit Entries
```
GET /admin/llm/audit?limit=100&agent=rca-agent&model=llama-3-70b
```

**Query Parameters:**
- `limit` - Max entries to return (default: 100, max: 1000)
- `agent` - Filter by agent name
- `model` - Filter by model name
- `provider` - Filter by provider name
- `status` - Filter by status (success, error, fallback)

**Response:**
```json
{
  "entries": [
    {
      "timestamp": "2025-01-15T14:30:00Z",
      "agent": "rca-agent",
      "model": "llama-3-70b-instruct",
      "provider": "vllm-prod",
      "request_id": "req-12345",
      "input_tokens": 2800,
      "output_tokens": 650,
      "latency_ms": 420,
      "cost_usd": 0.00235,
      "status": "success",
      "fallback_used": false,
      "fallback_count": 0
    },
    {
      "timestamp": "2025-01-15T14:29:45Z",
      "agent": "chatops-agent",
      "model": "gpt-4o",
      "provider": "openai",
      "request_id": "req-12344",
      "input_tokens": 1200,
      "output_tokens": 450,
      "latency_ms": 850,
      "cost_usd": 0.0185,
      "status": "error",
      "error_message": "Rate limit exceeded",
      "fallback_used": true,
      "fallback_count": 1,
      "fallback_model": "gpt-4o-mini"
    }
  ]
}
```

## Gateway Inference API

The gateway exposes OpenAI-compatible endpoints that all agents use.

### Chat Completions
```
POST /v1/chat/completions
X-Agent: rca-agent
Content-Type: application/json

{
  "messages": [
    {"role": "system", "content": "You are an RCA specialist."},
    {"role": "user", "content": "Analyze this vibration spike..."}
  ],
  "temperature": 0.7,
  "max_tokens": 4096,
  "stream": false
}
```

**Required Headers:**
- `X-Agent` - Agent name (used for routing, quotas, and audit logging)

**Optional Headers:**
- `Authorization: Bearer <token>` - For RBAC enforcement

**Response:**
```json
{
  "id": "chatcmpl-12345",
  "object": "chat.completion",
  "created": 1705330800,
  "model": "llama-3-70b-instruct",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "Based on the telemetry data..."
      },
      "finish_reason": "stop"
    }
  ],
  "usage": {
    "prompt_tokens": 2800,
    "completion_tokens": 650,
    "total_tokens": 3450
  },
  "_forgemind_metadata": {
    "provider": "vllm-prod",
    "routing_strategy": "highest_quality",
    "fallback_used": false,
    "cost_usd": 0.00235
  }
}
```

### List Models
```
GET /v1/models
```

**Response:**
```json
{
  "object": "list",
  "data": [
    {
      "id": "llama-3-70b-instruct",
      "object": "model",
      "created": 1705330800,
      "owned_by": "vllm-prod",
      "_forgemind_metadata": {
        "provider_id": "provider-uuid",
        "display_name": "Llama 3 70B Instruct",
        "capabilities": ["reasoning", "tools"],
        "enabled": true
      }
    }
  ]
}
```

## Example Usage

### Register a new OpenAI provider
```bash
curl -X POST http://localhost:8080/api/v1/admin/llm/providers \
  -H "Authorization: Bearer $JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "OpenAI Production",
    "kind": "cloud",
    "provider_type": "openai",
    "base_url": "https://api.openai.com/v1",
    "api_key": "sk-...",
    "enabled": true
  }'
```

### Register a local vLLM model
```bash
curl -X POST http://localhost:8080/api/v1/admin/llm/providers \
  -H "Authorization: Bearer $JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Local vLLM Server",
    "kind": "self_hosted",
    "provider_type": "vllm",
    "base_url": "http://vllm:8000/v1",
    "enabled": true
  }'

# Then register the model
curl -X POST http://localhost:8080/api/v1/admin/llm/models \
  -H "Authorization: Bearer $JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "provider_id": "<provider-id-from-above>",
    "model_name": "llama-3-70b-instruct",
    "display_name": "Llama 3 70B Instruct",
    "context_window": 8192,
    "max_output": 4096,
    "cost_per_input_tok": 0.0,
    "cost_per_output_tok": 0.0,
    "capabilities": ["reasoning", "tools"],
    "enabled": true
  }'
```

### Configure RCA agent to use the vLLM model
```bash
curl -X PUT http://localhost:8080/api/v1/admin/llm/agents/rca-agent/routing \
  -H "Authorization: Bearer $JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "primary_model_id": "<model-id-from-above>",
    "routing_strategy": "local_only",
    "temperature": 0.7,
    "max_tokens": 4096
  }'
```

### Set up fallback chain
```bash
curl -X PUT http://localhost:8080/api/v1/admin/llm/agents/rca-agent/fallback \
  -H "Authorization: Bearer $JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "fallback_model_ids": [
      "<local-model-id>",
      "<cloud-model-id-1>",
      "<cloud-model-id-2>"
    ]
  }'
```

This configuration ensures the RCA agent first tries the local vLLM model, and falls back to cloud providers if needed.
