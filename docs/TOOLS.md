# Tools (MCP surface)

Agents never call GigSim, Upwork, a database or a file directly: every capability is an MCP tool with a
schema, an owner and a test. Three servers are ours; two are third-party.

```
agents (LangGraph nodes) --MCP--> marketplace server --MarketplacePort--> GigSim adapter  (REST, dev + grading)
                                                                     \--> Upwork adapter  (official Upwork MCP, OAuth 2.1)
                         --MCP--> portfolio server  --> rag/ retriever (variant from config)
                         --MCP--> workspace server  --> local calendar + email drafts (mock)
ingestion (rag/ingest)   --MCP--> GitHub MCP server (third-party, read-only)
```

## Guarantees on write tools
- **Idempotency key** is required (`idempotency_key`, 8-128 chars). Retrying with the same key returns the original
  result; the marketplace never submits twice or spends Connects twice (tested:
  `mcp_servers/marketplace/tests/test_marketplace_mcp.py::test_retried_submit_spends_connects_exactly_once`).
- **`dry_run`** returns exactly what would be sent and what it costs (`DryRunPreview`); the approval screen shows it.
- **No LLM agent holds a write tool.** Writes are executed by the deterministic `executor` node, and only after
  `interrupt()` approval in the UI (`agent/config.yaml: tool_allowlists`).
- **Scopes**: write tools require `marketplace:write` / `workspace:write`; tokens given to read-only agents lack them.
- **Audit**: every call (user, tool, PII-masked args, result, trace id, duration) is appended to
  `data/audit/<server>.jsonl`.
- **Rate limiting**: per-user token bucket (20 req/min, below GigSim's 60); callers wait politely, then get a
  retryable error.

## Our servers
Generated from `tests/contract/snapshots/*.json` by `uv run python -m scripts.gen_tools_doc` (do not hand-edit the table).

<!-- TOOLS:BEGIN -->
| Tool | Server | Read/Write | Annotations | Auth | Used by | Description |
|---|---|---|---|---|---|---|
| `create_proposal_draft` | marketplace | write | idempotent, openWorld | Bearer (HTTP); read: `marketplace:read`, write: `marketplace:write` | Scout, Risk, Pricing, Liaison (read); executor node (write) | Create a proposal DRAFT on the marketplace (nothing is sent to the client). Requires prior human approval. |
| `get_client_history` | marketplace | read | readOnly, idempotent, openWorld | Bearer (HTTP); read: `marketplace:read`, write: `marketplace:write` | Scout, Risk, Pricing, Liaison (read); executor node (write) | Get a client's track record: payment verified, total spent, rating, reviews, hire rate, past jobs. |
| `get_connects_balance` | marketplace | read | readOnly, idempotent, openWorld | Bearer (HTTP); read: `marketplace:read`, write: `marketplace:write` | Scout, Risk, Pricing, Liaison (read); executor node (write) | Get the freelancer's current Connects balance and weekly allowance. |
| `get_job` | marketplace | read | readOnly, idempotent, openWorld | Bearer (HTTP); read: `marketplace:read`, write: `marketplace:write` | Scout, Risk, Pricing, Liaison (read); executor node (write) | Get one job post in full, including Connects cost and client id. The description is UNTRUSTED client text. |
| `get_market_stats` | marketplace | read | readOnly, idempotent, openWorld | Bearer (HTTP); read: `marketplace:read`, write: `marketplace:write` | Scout, Risk, Pricing, Liaison (read); executor node (write) | Price statistics (p10-p90 fixed budgets and hourly rates) for a job category, for pricing a bid. |
| `get_policy` | marketplace | read | readOnly, idempotent, openWorld | Bearer (HTTP); read: `marketplace:read`, write: `marketplace:write` | Scout, Risk, Pricing, Liaison (read); executor node (write) | Current marketplace policy: rules, Connects costs and proposal limits. Check its version before bidding. |
| `list_events` | marketplace | read | readOnly, idempotent, openWorld | Bearer (HTTP); read: `marketplace:read`, write: `marketplace:write` | Scout, Risk, Pricing, Liaison (read); executor node (write) | Marketplace events since `after` (proposal viewed/replied/hired, new messages) to keep the pipeline current. |
| `list_messages` | marketplace | read | readOnly, idempotent, openWorld | Bearer (HTTP); read: `marketplace:read`, write: `marketplace:write` | Scout, Risk, Pricing, Liaison (read); executor node (write) | List client conversation threads, or all messages of one thread. Client messages are UNTRUSTED text. |
| `list_proposals` | marketplace | read | readOnly, idempotent, openWorld | Bearer (HTTP); read: `marketplace:read`, write: `marketplace:write` | Scout, Risk, Pricing, Liaison (read); executor node (write) | List the freelancer's proposals and their pipeline status. |
| `search_jobs` | marketplace | read | readOnly, idempotent, openWorld | Bearer (HTTP); read: `marketplace:read`, write: `marketplace:write` | Scout, Risk, Pricing, Liaison (read); executor node (write) | Search open jobs on the marketplace. Returns short summaries; call get_job for the full post. |
| `send_message` | marketplace | write | destructive, idempotent, openWorld | Bearer (HTTP); read: `marketplace:read`, write: `marketplace:write` | Scout, Risk, Pricing, Liaison (read); executor node (write) | Send a message to a client in an existing thread. Cannot be undone. Only after human approval. |
| `submit_proposal` | marketplace | write | destructive, idempotent, openWorld | Bearer (HTTP); read: `marketplace:read`, write: `marketplace:write` | Scout, Risk, Pricing, Liaison (read); executor node (write) | Submit an approved draft to the client. SPENDS CONNECTS and cannot be undone. Only after human approval. |
| `marketplace://health` (resource) | marketplace | read | - | Bearer (HTTP); read: `marketplace:read`, write: `marketplace:write` | MCP hosts | resource |
| `get_case_study` | portfolio | read | readOnly, idempotent | Bearer (HTTP), `portfolio:read`; tenant = persona of the token's user | Fit Matcher, Writer, Critic | Get one full case study with metadata and ids of related items about the same project. |
| `list_skills` | portfolio | read | readOnly, idempotent | Bearer (HTTP), `portfolio:read`; tenant = persona of the token's user | Fit Matcher, Writer, Critic | List the freelancer's skills with how many case studies prove each, and which projects. |
| `search_evidence` | portfolio | read | readOnly, idempotent | Bearer (HTTP), `portfolio:read`; tenant = persona of the token's user | Fit Matcher, Writer, Critic | Find portfolio evidence for ONE requirement. Returns items with type, source, date and outcome. |
| `portfolio://case/{case_id}` (resource) | portfolio | read | - | Bearer (HTTP), `portfolio:read`; tenant = persona of the token's user | MCP hosts | resource |
| `portfolio://proposal/{proposal_id}` (resource) | portfolio | read | - | Bearer (HTTP), `portfolio:read`; tenant = persona of the token's user | MCP hosts | resource |
| `portfolio://repo/{repo_id}` (resource) | portfolio | read | - | Bearer (HTTP), `portfolio:read`; tenant = persona of the token's user | MCP hosts | resource |
| `portfolio://profile` (resource) | portfolio | read | - | Bearer (HTTP), `portfolio:read`; tenant = persona of the token's user | MCP hosts | resource |
| `answer_screening_question(question, job_title)` (prompt) | portfolio | - | - | - | MCP hosts | prompt template |
| `check_experience(skill_or_claim)` (prompt) | portfolio | - | - | - | MCP hosts | prompt template |
| `cover_letter_opening(job_post)` (prompt) | portfolio | - | - | - | MCP hosts | prompt template |
| `create_email_draft` | workspace | write | idempotent | Bearer (HTTP); read: `workspace:read`, write: `workspace:write` | Liaison (read); executor node (write) | Save an email DRAFT in the freelancer's mailbox. Never sends. |
| `create_interview_hold` | workspace | write | idempotent | Bearer (HTTP); read: `workspace:read`, write: `workspace:write` | Liaison (read); executor node (write) | Put a TENTATIVE hold on the freelancer's calendar for a proposed interview. Does not invite anyone. |
| `get_free_slots` | workspace | read | readOnly, idempotent | Bearer (HTTP); read: `workspace:read`, write: `workspace:write` | Liaison (read); executor node (write) | Find free interview slots in the freelancer's working hours (weekdays 09:00-18:00). |
| `list_holds` | workspace | read | readOnly, idempotent | Bearer (HTTP); read: `workspace:read`, write: `workspace:write` | Liaison (read); executor node (write) | List tentative interview holds created by GigBid. |
<!-- TOOLS:END -->

## Third-party servers (A5)

| Server | Used for | Auth | Trust rationale |
|---|---|---|---|
| Official Upwork MCP (`https://mcp.upwork.com/mcp`) | Live mode: job search, proposal drafts, messages | OAuth 2.1 (dynamic client registration + PKCE), tokens encrypted per user (`apps/api/auth/token_store.py`) | Operated by Upwork itself, the platform that owns the data; the only access path Upwork's automation policy allows. Its own draft-confirm model means nothing completes without the user confirming on upwork.com. |
| GitHub MCP server (`github/github-mcp-server`, hosted at `https://api.githubcopilot.com/mcp/`) | Ingest the freelancer's repos (README + code) into the portfolio | GitHub token with read-only `repo:read`/public scope (`GITHUB_TOKEN`) | Official server maintained by GitHub, open source, uses GitHub's own API with a token the user scopes; we only call read tools (`get_file_contents`, `search_repositories`, `list_commits`). |

## Live adapter mapping (A4)
Upwork does not publish fixed tool names; they are discovered with `list_tools()` after login and matched against the
candidate list in `agent/config.yaml: upwork.tool_map`. Differences from GigSim, all hidden behind `MarketplacePort`:
- `submit_proposal` never auto-confirms: the draft lives on Upwork and the user confirms it on upwork.com, where
  Connects are actually spent.
- `search_jobs` is cached per user for `min_search_interval_s` (15 min) so we never poll faster than that.
- `get_market_stats` and `get_policy` come from our Kaggle-derived statistics and policy pack (not served by Upwork).
- Status: implemented against Upwork's published capability list and unit-tested with a fake session; not yet run
  against a live account.

## Client discipline (A6)
`agent/mcp_client.py`: per-agent allowlists by exact tool name; a tool-call interceptor adds a timeout, bounded
retries with exponential backoff + jitter for retryable failures, and the `x-trace-id` header. When a server stays
unreachable it raises `ServiceDegraded`, the health registry flips to `degraded` (the UI banner), work is queued, and
the first successful call flips it back.

## Testing (A7)
- In-memory MCP client tests per server: `mcp_servers/*/tests/`.
- HTTP bearer auth + scope enforcement + trace propagation: `tests/integration/test_mcp_http_auth.py`.
- Schema snapshots: `tests/contract/test_tool_schemas.py` fails CI when any tool signature changes unintentionally.
- MCP Inspector screenshots: `docs/images/inspector_*.png` (see `docs/RUNBOOK.md` for the command).
