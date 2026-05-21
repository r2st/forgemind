# ForgeMind AI — End-to-End Test Suite

**289 tests · 96% line coverage · ≈20s wall time · zero external dependencies.**

This suite verifies every user-visible behaviour of the ForgeMind stack without
spinning up Docker, Postgres, NATS, or any real LLM provider. Every one of the
12 backend services runs in-process via FastAPI's `TestClient` (or `httpx`'s
`ASGITransport` for async-only coverage).

## Quick start

```bash
# From the repo root
python3 -m pytest tests/e2e/
```

With coverage (the repo's `.coveragerc` enables `concurrency=thread,greenlet`,
which is required for coverage to see into FastAPI's anyio-driven request
handling):

```bash
python3 -m pytest tests/e2e/ \
  --cov=shared/forgemind_common --cov=services \
  --cov-config=.coveragerc --cov-report=term-missing
```

Install requirements once:

```bash
pip install fastapi==0.110.0 'uvicorn[standard]==0.27.1' httpx==0.27.0 \
  pydantic==2.6.4 pydantic-settings==2.2.1 structlog==24.1.0 \
  prometheus-client==0.20.0 nats-py==2.7.2 'sqlalchemy[asyncio]==2.0.29' \
  aiosqlite numpy==1.26.4 'python-jose[cryptography]==3.3.0' \
  cryptography==42.0.2 pgvector==0.2.5 python-multipart==0.0.6 \
  scikit-learn==1.4.1.post1 asyncpg==0.29.0 langgraph \
  pytest pytest-asyncio pytest-cov
```

## How the harness works

`conftest.py` is the keystone. It sets up a fully in-process stack:

1. **Path setup.** `shared/` and each `services/<svc>` directory go on
   `sys.path` so every service's `app.main` can import `forgemind_common` and
   relative `.schemas` siblings.

2. **Environment defaults.** `POSTGRES_DSN` points at SQLite-in-memory with
   `cache=shared` so all services see the same DB. `JWT_SECRET` and admin
   credentials are set so the API gateway's auth flow works.

3. **pgvector shim.** `pgvector.sqlalchemy.Vector(dim)` is replaced with a
   SQLAlchemy `TypeDecorator` over `JSON` so the RCA service's
   `IncidentMemory.embedding` column can be created on SQLite. The
   `CREATE EXTENSION IF NOT EXISTS vector` statement is silently no-op'd on
   the sqlite dialect by wrapping `AsyncConnection.execute`.

4. **In-memory NATS broker.** `forgemind_common.messaging.publish` and
   `subscribe` are monkey-patched with an in-process pub/sub broker so the
   anomaly-detection, notification-service, and telemetry-ingestion publish
   paths work without a real NATS server.

5. **Mocked LLM gateway.** `LLMGateway.chat` and `.embed` are replaced with a
   deterministic responder that inspects the agent's system prompt and returns
   a shape-correct response (RCA JSON, severity JSON, plain-text chat, etc.).
   The originals are captured in `REAL_LLM_GATEWAY_METHODS` so
   `test_llm_gateway_client.py` can restore them inside a scoped fixture to
   exercise the real HTTP code path.

6. **Routing transport.** A custom `httpx.AsyncBaseTransport` is installed on
   every `httpx.AsyncClient` created in-process. It maps internal hostnames
   (`http://anomaly-detection:8000`, `http://telemetry-simulator:8000`, …) to
   the matching service's `ASGITransport`, so inter-service HTTP calls are
   routed locally instead of hitting the network.

7. **Service registry.** `service_apps` is a session-scoped fixture that loads
   each service's FastAPI app once and registers it with the routing
   transport. Each `<service>_client` fixture wraps a `TestClient` and runs
   the service's lifespan (creating SQLite tables, etc.).

## Test layout

| File | What it covers |
|---|---|
| `test_smoke.py` | Service-apps fixture, sanity check |
| `test_telemetry_simulator.py` | `/machines`, `/snapshot`, `/inject`, `/replay-historical` |
| `test_telemetry_ingestion.py` | Batch and single ingest, validation, broker publish |
| `test_anomaly_detection.py` | `/score` warmup + spike, `/incidents` filtering |
| `test_severity_and_anomaly_internals.py` | LLM-assisted severity classifier + heuristic fallback, IsolationForest training, MachineSim anomaly branches |
| `test_subscriber_pipelines.py` | `_handle_reading`, `_record_anomaly`, RCA machine-id extraction loop, error paths |
| `test_rca_service.py` | RCA run, list, get, agent activity |
| `test_rca_internals.py` | `parse_rca_json`, tool registry, embed-failure fallbacks |
| `test_ai_orchestrator.py` | Agents listing, supervisor run, activity ledger |
| `test_agents_and_supervisor.py` | Every specialist tool handler (monitoring/PdM/optimization/reporting), `delegate_to_agent`, `list_specialists` |
| `test_workflow_engine.py` | All 4 LangGraph graphs end-to-end |
| `test_workflow_nodes.py` | Every workflow node function in isolation, including failure branches |
| `test_chatops_service.py` | Chat, session persistence, SSE streaming |
| `test_reporting_service.py` | Report generate, list, get |
| `test_pdm_service.py` | Predictions, per-machine, explain |
| `test_notification_service.py` | Recent notifications, flood suppression |
| `test_api_gateway.py` | Auth, RBAC, admin endpoints, reverse proxy |
| `test_llm_gateway.py` | Health, providers, models, audit/usage/cost/health (basic) |
| `test_llm_gateway_admin.py` | Deep CRUD for providers/models/routing/fallback chains |
| `test_llm_gateway_inference.py` | `/v1/chat/completions` happy path, fallback chain, quota enforcement, JWT |
| `test_llm_gateway_extra.py` | Usage/health/cost/audit endpoints with real data |
| `test_llm_gateway_branches.py` | Branch coverage of every CRUD update path |
| `test_llm_gateway_client.py` | Real `LLMGateway.chat`/`.embed`/`.chat_stream` HTTP paths |
| `test_translators.py` | OpenAI / Anthropic / Gemini request + response translators |
| `test_llm_client.py` | `forgemind_common.llm_client.LLMClient` chat + streaming |
| `test_messaging.py` | Real NATS `publish`/`subscribe`/`iter_messages` with stubbed client |
| `test_hermes_runtime.py` | LiteAgent loop, tool dispatch, unknown-tool branch, Hermes init paths |
| `test_runtime_config.py` | JSON config load/save, agent overrides, provider normalization |
| `test_helpers.py` | Pure helpers: `_decayed_risk`, `_chunk_text`, `_sse`, MachineSim |
| `test_misc_coverage.py` | Rate limit, proxy 502, SSRF URL validation, db helpers |
| `test_async_inproc.py` | Async ASGI tests that bypass TestClient threading |
| `test_full_flow.py` | True end-to-end demo: replay → incident → investigation → report → chat |
| `test_final_coverage.py` | Lifespan tasks, pump-loop exception branch, workflow error path |
| `test_extra_coverage.py` | Schema validators, RCA tool handlers, admin proxy edge cases |

## Coverage measurement

Coverage uses `concurrency = thread,greenlet` so the tracer follows into
Starlette/anyio's request-dispatch threads. Without that setting, FastAPI
handler bodies appear to be 0% covered even though they ran successfully.
The config lives in `.coveragerc` at the repo root.

## What's intentionally not covered

The remaining ~4% of uncovered lines are infeasible to exercise in this harness:

- `if __name__ == "__main__":` blocks (uvicorn entry points)
- Infinite background loops (`while True: await asyncio.sleep(3600)`)
- pgvector `cosine_distance(...)` SQL paths (require real Postgres + pgvector)
- Real Hermes `_run_hermes` paths (require the proprietary `run_agent` package)
- A couple of JWT validation branches behind unreachable token shapes
