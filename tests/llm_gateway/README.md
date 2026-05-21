# LLM Gateway Tests

Comprehensive test suite for the ForgeMind AI LLM Gateway service.

## Test Coverage

### Provider Management (`test_provider_crud.py`)
- Create, read, update, delete providers
- API key encryption at rest
- Provider validation
- Cloud and self-hosted provider types

### Model Registry (`test_model_crud.py`)
- Create, read, update, delete models
- Model-provider relationships
- Model validation
- Cost configuration

### Routing Configuration (`test_routing.py`)
- Agent routing configuration
- Routing strategy validation (cheapest, lowest_latency, highest_quality, etc.)
- Per-agent configuration overrides
- Default routing behavior

### Fallback Chain (`test_fallback.py`)
- Fallback chain configuration
- Order preservation
- Primary model success (no fallback)
- Primary model failure → fallback execution
- Multiple fallback attempts

### Provider Translation (`test_translation.py`)
- OpenAI-compatible passthrough (OpenAI, vLLM, Together, Groq, etc.)
- Anthropic request/response translation
- Model-specific request formatting

### Audit & Quotas (`test_audit.py`)
- Audit log recording of all inference calls
- Audit log filtering (by agent, model, provider, status)
- Per-agent quota enforcement (request count, token budget)
- Cost tracking and calculation

### Health Monitoring (`test_health.py`)
- Provider health probes
- Health status (healthy, degraded, unhealthy)
- Latency tracking
- Usage analytics aggregation

## Running Tests

### Run all LLM Gateway tests
```bash
pytest tests/llm_gateway -v
```

### Run specific test file
```bash
pytest tests/llm_gateway/test_provider_crud.py -v
```

### Run specific test
```bash
pytest tests/llm_gateway/test_routing.py::test_per_agent_override -v
```

### Run with coverage
```bash
pytest tests/llm_gateway --cov=services/llm-gateway --cov-report=html
```

### Stop on first failure
```bash
pytest tests/llm_gateway -x
```

## Requirements

The tests require:
- `pytest`
- `pytest-asyncio`
- `fastapi[all]`
- `httpx`
- `cryptography`
- `sqlalchemy`

Install test dependencies:
```bash
pip install -r services/llm-gateway/requirements.txt
pip install pytest pytest-asyncio
```

## Test Architecture

### Fixtures (`conftest.py`)
- `client`: FastAPI TestClient with in-memory SQLite database
- `sample_provider_data`: Template provider configuration
- `sample_model_data`: Template model configuration
- `sample_routing_config`: Template agent routing config

### Mocking Strategy
- HTTP requests to external providers are mocked using `unittest.mock.patch`
- Database is in-memory SQLite (fresh for each test)
- No external services required

### Test Isolation
- Each test gets a fresh database
- No state shared between tests
- Tests can run in parallel

## Coverage Goals

Target: >90% code coverage for LLM Gateway service

Current coverage areas:
- [x] Provider CRUD operations
- [x] Model CRUD operations
- [x] Routing configuration
- [x] Fallback chain execution
- [x] Request/response translation
- [x] Audit logging
- [x] Quota enforcement
- [x] Cost tracking
- [x] Health monitoring
- [x] Usage analytics

## CI/CD Integration

These tests run automatically on:
- Every commit to `main`
- Every pull request
- Pre-deployment validation

Failures block deployment.
