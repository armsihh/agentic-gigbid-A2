# Runbook

## Local development
```bash
uv sync                      # Python 3.12 env from uv.lock
make data                    # only if regenerating the world from Kaggle CSVs (data/raw/kaggle)
make gigsim                  # GigSim on :8081 (GIGSIM_TIME_SCALE=60 for fast demos)
make mcp-http                # marketplace :8101, portfolio :8102, workspace :8103 (Streamable HTTP)
make test                    # all tests
```
The MCP servers also run over stdio (`uv run python -m mcp_servers.<name>.server`); that is what
`agent/mcp_client.py` spawns by default. Set `MARKETPLACE_MCP_URL` etc. to use the HTTP servers instead.

## MCP Inspector (screenshots for the submission)
```bash
npx @modelcontextprotocol/inspector uv run python -m mcp_servers.portfolio.server
npx @modelcontextprotocol/inspector uv run python -m mcp_servers.marketplace.server
npx @modelcontextprotocol/inspector uv run python -m mcp_servers.workspace.server
```
Set `PORTFOLIO_PERSONA=ai_ml` (and have GigSim running for the marketplace). Save screenshots of the tool list,
a `search_evidence` call, and a `create_proposal_draft` dry run to `docs/images/inspector_*.png`.

## Rate limits and scheduling
| Layer | Limit | Where |
|---|---|---|
| GigSim (simulated platform) | 60 req/min per token, burst 20 -> 429 + Retry-After | `gigsim/config.yaml` |
| Our marketplace MCP server | 20 req/min per user; callers wait up to 10 s, then a retryable error | `agent/config.yaml: marketplace.max_requests_per_minute` |
| Live Upwork job search | at most once per 15 min per user per query (cached) | `agent/config.yaml: upwork.min_search_interval_s` |

Why 15 minutes in live mode: a human freelancer checks the feed a few times an hour at most, new matching jobs per
saved search arrive at roughly that rate, and Upwork's automation guidance treats aggressive polling as scraping-like.
Faster polling would not find meaningfully more jobs but would look like a bot.

## Degraded mode (marketplace down)
1. The GigSim adapter retries transient failures (connect errors, 429 with Retry-After, 5xx) with exponential
   backoff + jitter, bounded at 4 attempts; then raises `MarketplaceUnavailable`.
2. The MCP server returns a tool error tagged `[marketplace_unavailable retryable]`.
3. `agent/mcp_client.py`'s interceptor retries (bounded), then raises `ServiceDegraded` and marks the server
   `degraded` in the health registry (`health.snapshot()`), which the API exposes and the UI shows as a banner.
4. Graph threads that hit `ServiceDegraded` pause in a queued state instead of failing; the worker retries them on
   its next tick, and the first successful call marks the server healthy again.

Viva drill: `kill` the GigSim (or marketplace MCP) process -> banner appears, jobs queue -> restart -> recovers.

## Idempotency and exactly-once
Every write carries an idempotency key derived from the thread and action (e.g. `submit:<thread_id>:<proposal_id>`),
so a retried or replayed call returns the original result. GigSim stores keys per account; Connects are deducted once.

## Secrets
Only from environment variables (`.env` locally, host secrets in deployment); `.env.example` lists them all.
OAuth tokens are encrypted at rest with a key derived from `APP_SECRET_KEY` (`apps/api/auth/token_store.py`);
rotating `APP_SECRET_KEY` invalidates stored tokens (users reconnect). Audit logs and traces are PII-masked.
