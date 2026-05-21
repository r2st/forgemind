# Live TrueFoundry Deploy — Report

Date: 2026-05-21
Account: sumaninster7@gmail.com (display name "sumaninste...")
Tenant: truefoundry (managed demo tier)
TFY host: https://app.truefoundry.com
AI Gateway: https://gateway.truefoundry.ai

## What worked

1. **Personal Access Token** — created via the UI ("forgemind-deploy"), captured into the keys folder. `tfy login` succeeded:
   `Logged in to 'https://app.truefoundry.com' as 'forgemind-deploy'`.
2. **GitHub push** — project pushed to https://github.com/r2st/forgemind, main branch. Service specs now build from this git URL.
3. **AI Gateway end-to-end** — verified live by routing a chat completion through the gateway via our `TrueFoundryGateway` client:
   - model: `openai-main/gpt-4o-mini` → returned `gpt-4o-mini-2024-07-18`
   - latency: ~744 ms
   - prompt 42 tok / completion 19 tok / cached=False
   - 230 models discovered on the gateway (15 from `openai-main`, 14 from `test-anthropic`, plus self-hosted and others).

This is the core integration claim of ForgeMind: *Hermes routes its LLM calls through TrueFoundry*. That path is provably live.

## What didn't (yet)

**Service deploy returned 403.** The only workspaces this account can see are:
- `tfy-usea1-demo:tfy-logs` (cluster `tfy-usea1-demo`, us-east-1)
- `tfy-eaus-demo:tfy-logs` (cluster `tfy-eaus-demo`)

Both are `isSystemWs: true` with `collaborators: [{role: workspace-viewer, subject: team:everyone}]` — viewer-only. Attempting to deploy `forgemind-telemetry-simulator` returned:

```
Status Code  403
Error        User does not have the manage application permission on the workspace
```

To finish the service deploy: provision a workspace where this account has the `workspace-deployer` role (or higher). Then re-run:

```bash
export TFY_API_KEY=$(cat keys/PAT_truefoundry)
./infra/truefoundry/deploy.sh
```

with `TFY_WORKSPACE` set to the writable workspace FQN. Every service spec in `infra/truefoundry/services/*.yaml` already builds from `github.com/r2st/forgemind` ref `main`.

## Discovered values

- Cluster domain: `*.aws.demo.truefoundry.cloud`
- Working FAST model: `openai-main/gpt-4o-mini`
- Working POWERFUL model: `openai-main/gpt-4o`
- Working Anthropic-style fallback: `test-anthropic/claude-3-5-haiku-20241022`

These are now hard-coded into `.env.example` and `shared/forgemind_common/config.py` defaults.
