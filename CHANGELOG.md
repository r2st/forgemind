# Changelog

## Unreleased

### Added

- **End-to-end test suite** under `tests/e2e/` — 289 tests, 96% line coverage,
  zero external dependencies. Runs every service in-process via FastAPI
  `TestClient`, with in-memory NATS broker, SQLite-backed Postgres replacement,
  pgvector → JSON shim, mocked LLM gateway, and an ASGI routing transport that
  wires the 12 services together. See [`tests/e2e/README.md`](tests/e2e/README.md).
- **`.coveragerc`** at the repo root with `concurrency = thread,greenlet` so
  coverage correctly traces handler execution inside FastAPI/anyio's worker
  threads.
- **Testing section** in the top-level README with install + run instructions.

### Fixed

- **`services/llm-gateway/app/main.py:326`** — `update_provider` performed a
  runtime relative import (`from .schemas import validate_base_url, ProviderKind`)
  inside the handler. In environments where `sys.modules['app.schemas']` is not
  resident (multi-service test harnesses, certain reload scenarios), this raised
  `ModuleNotFoundError` and surfaced as a misleading 404 to clients changing a
  provider's `base_url`. Imports moved to the module-level `from .schemas import (…)`
  block.
- **`tests/llm_gateway/conftest.py`** — Pre-existing import bug: `shared/` was
  never added to `sys.path`, so the unit suite couldn't import at all. Fixed
  alongside `JWT_SECRET` defaulting.

### Notes

The new E2E suite is the canonical regression harness going forward. It runs in
about 20 seconds on a modern laptop and requires no Docker, no Postgres, and no
real LLM provider. CI should run it on every PR.
