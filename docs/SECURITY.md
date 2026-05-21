# Security Model

## Authentication

JWT (HS256) issued by the API gateway. Tokens carry `sub`, `role`, `exp`.

Roles (`admin > engineer > operator > viewer`):

- `viewer` — read-only. List incidents, view dashboards.
- `operator` — viewer + inject anomalies, ack incidents, trigger RCA.
- `engineer` — operator + run workflows, generate reports, approve maintenance.
- `admin` — all of the above + settings.

Use `require_role(...)` in any FastAPI endpoint:

```python
@app.post("/foo", dependencies=[Depends(require_role("engineer"))])
```

## Rate limiting

Per-IP token bucket at the API gateway: 300 req / 60 s window. Returns `429 Too Many Requests` when exceeded.

## Secrets

Never in container images. Sources, in order of preference:

1. **Kubernetes secrets** — mounted via `secretRef` in the Helm chart.
2. **Admin runtime config** — shared JSON volume for per-agent API keys, file mode `0600`.
3. **Dev only** — `.env` file at the repo root (gitignored).

## Audit

- The configured LLM API or private gateway may emit trace/request IDs.
- Each FastAPI service emits structured JSON logs to stdout so Loki, Datadog, or platform log collectors can pick them up.
- The `forgemind_llm_tokens_total` and `forgemind_llm_cost_usd` Prom counters are per-service / per-tier / per-model for chargeback.

## Approval workflows

The LangGraph `investigation` and `maintenance_approval` graphs include an `approval_gate` node. When severity ≥ HIGH (investigation) or PdM risk > 0.4 (maintenance), the graph emits `status: blocked_on_approval` and stops. The frontend exposes Approve / Reject; the workflow resumes via `POST /workflows/<name>/run` with `approved=true`.

## PII

PII redaction depends on the configured LLM gateway. If operator notes may carry
personal data, enable redaction at your gateway boundary before forwarding
prompts to an external model provider.
