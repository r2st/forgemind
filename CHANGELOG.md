# Changelog

## Unreleased

### Added — user management from the Admin Panel

- **Persistent, bcrypt-hashed auth store** in
  `shared/forgemind_common/auth_store.py`. Users are stored in
  `auth_users.json` next to the agent config, mode `0600`, with a small
  in-process TTL cache for fast logins.
- **Admin Panel "Users" section** (`frontend/src/views/AdminPanel.vue`)
  with list, add, edit, delete, and "Move env user to store" actions.
- **API endpoints**, admin-only:
  - `GET /api/v1/admin/auth/users` — list store users plus env-var
    bootstrap users
  - `PUT /api/v1/admin/auth/users/{username}` — upsert (create / update
    role / reset password)
  - `DELETE /api/v1/admin/auth/users/{username}` — delete (refuses to
    delete the currently logged-in admin)
- **Login precedence**: store first, env-var fallback only when the
  username isn't in the store. Defense against leftover env vars after
  a user is rotated.
- **22 new E2E tests** in `tests/e2e/test_auth_store.py`.

### Changed

- `docker-compose.yml`: `AUTH_*_PASS` and `GRAFANA_ADMIN_PASSWORD` now
  have safe defaults so `docker compose up` no longer emits "variable
  not set" warnings on a fresh checkout. **These are bootstrap-only**
  — once an admin manages users from the panel, the store entries take
  precedence.
- `.env.example`: AUTH_* section relabeled "bootstrap credentials" to
  match the new behaviour.
- `services/api-gateway/requirements.txt` and `shared/pyproject.toml`:
  add `bcrypt>=4.0`.

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
