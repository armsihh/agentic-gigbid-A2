# GigSim API contract (v1)

GigSim is the marketplace simulator GigBid develops and is graded against. The assignment
described GigSim as provided, but the starter kit did not include it, and the instructor's
follow-up said to build our own from the Kaggle datasets. This is that build.

**Replaceability rule:** nothing in GigBid imports `gigsim.*`. The only consumer is
`mcp_servers/marketplace/adapters/gigsim.py`, which speaks this HTTP contract. If an official
GigSim is released later, only that adapter (field mapping) changes.

Run: `uv run uvicorn gigsim.app:app --port 8081` (interactive docs at `/docs`).

## Conventions
- Auth: `Authorization: Bearer <token>`. Each token maps to one freelancer account (`config.yaml` / `GIGSIM_TOKENS`).
- Errors: `{"error": {"code": "...", "message": "...", ...}}` with a meaningful HTTP status.
- Writes (`POST`) require an `Idempotency-Key` header. Replaying the same key + body returns the
  original response with `Idempotent-Replay: true`; the same key with a different body returns `409`.
- `dry_run: true` on any write returns exactly what would happen (including Connects cost) with no side effects
  and no key needed.
- Rate limit: token bucket per token (default 60 rpm, burst 20) -> `429` + `Retry-After`.
- Faults: ~3% of requests fail with `503 service_unavailable` **before** any side effect (safe to retry);
  ~2% are slow (3 s). Tune with `GIGSIM_ERROR_RATE`, `GIGSIM_SLOW_RATE`.

## Endpoints
| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | liveness + policy version (no auth) |
| GET | `/v1/policy` | current marketplace policy (rules, Connects, proposal limits) |
| GET | `/v1/me` | account summary |
| GET | `/v1/connects` | Connects balance and allowance |
| GET | `/v1/jobs` | search open jobs: `q`, `category`, `skills` (repeatable), `payment_type`, `min_budget`, `posted_after` (ISO), `limit`, `cursor` -> `{items, total, next_cursor}` (descriptions truncated to 280 chars) |
| GET | `/v1/jobs/{job_id}` | full job (includes `connects_cost`, `client_id`) |
| GET | `/v1/clients/{client_id}` | public client profile: payment verified, total spent, rating, reviews, hire rate, recent jobs |
| GET | `/v1/market/stats` | price quantiles by `category` (+ `experience_level`) |
| POST | `/v1/proposals` | create a **draft** `{job_id, cover_letter, screening_answers[], bid_amount, boost_connects, dry_run}` |
| POST | `/v1/proposals/{id}/submit` | submit a draft `{confirm: true, dry_run}`; spends Connects exactly once |
| GET | `/v1/proposals[?status=]`, `/v1/proposals/{id}` | proposal status: `draft, submitted, viewed, replied, interview, hired, lost` |
| GET | `/v1/threads`, `/v1/threads/{id}` | client conversations |
| POST | `/v1/threads/{id}/messages` | send a message `{text, dry_run}` |
| GET | `/v1/events?after=<seq>` | event feed for pipeline updates (`proposal.viewed`, `proposal.replied`, `message.received`, `proposal.hired`, ...) |

Admin (simulation control, `Bearer <admin_token>`): `POST /admin/advance?batches=n` (release jobs from the
stream now), `POST /admin/fast-forward` (fire all pending client events now), `POST /admin/reset`,
`GET /admin/state`.

## Policy enforcement on writes
- Cover letter length limits; contact details (email, phone, WhatsApp/Telegram...) -> `422 policy_violation` with `rule`.
- Submit requires `confirm: true` (human confirmation), Connects balance (`402 insufficient_connects`) and an
  open-proposal cap.
- All rules live in `gigsim/policy.yaml` (served at `/v1/policy`); the change request edits that file.

## Simulated clients
Each client has hidden preferences (`clients_hidden.jsonl`, never served): must-have skills, a budget ceiling,
dislike of generic openings, and reply propensity. On submit the simulator scores the proposal
(`gigsim/client_sim.py`) and schedules: viewed -> reply (question / interview request / negotiation) or lost.
Proposing a concrete time slot in a thread moves it to `interview`, then hired or lost. Scam clients reply
with off-platform or upfront-payment asks. Outcomes are deterministic per proposal text (seeded).
Calibration (`reply_scale` in `config.yaml`): generic ~3%, vague ~10%, specific evidence-backed ~30% reply.

## Time
Everything is lazy: each request first fires due events and releases due jobs. The job stream releases
`batch_size` jobs every `interval_seconds`. `GIGSIM_TIME_SCALE=60` makes all delays 60x shorter for demos.
