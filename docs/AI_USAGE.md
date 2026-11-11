# AI Usage Disclosure

**Tool:** Claude Code (Anthropic, model Claude Opus 5.5), used as a pair programmer in the terminal.
I reviewed, ran and tested every change; I am responsible for all code in this repository.

## What it helped with
| Area | Files |
|---|---|
| Kaggle preprocessing + synthetic world generation | `scripts/data/*` |
| GigSim simulator | `gigsim/*` |
| Marketplace port + adapters | `agent/marketplace_port.py`, `mcp_servers/marketplace/adapters/*` |
| MCP servers + shared plumbing | `mcp_servers/*`, `agent/mcp_client.py`, `agent/guardrails/pii.py` |
| OAuth token store / broker | `apps/api/auth/*` |
| Tests and docs | `tests/*`, `mcp_servers/*/tests/*`, `docs/*` |

## Things it got wrong that were caught
1. **GigSim outcomes were not reproducible.** The client simulator seeded its random number generator with the
   proposal's random UUID, so the same proposal to the same job could get a different reply on each run, which
   would have made reply-rate evaluations noisy. Caught by a flaky test; fixed by seeding from the proposal content
   (job, bid, text hash) and adding `test_outcomes_are_deterministic_per_proposal_content`.
2. **Interview holds conflicted with themselves on retry.** The Workspace server checked for calendar clashes before
   looking up the idempotency key, so a retried `create_interview_hold` failed against the hold it had just created.
   Caught in a smoke test; fixed by replaying idempotent results first.
3. **Reply rates were unrealistically high** (~81% for a specific proposal) in the first client-simulator calibration,
   leaving no headroom to measure improvements. Recalibrated to ~3% generic / ~30% specific (`reply_scale`).
4. A first data-preprocessing version ran 400 separate regexes per job and took over 10 minutes; replaced with one
   combined pattern (2.5 minutes).
5. **A formatter fix deleted evidence.** Running `ruff --fix` over the whole repo removed the "unused" imports from
   the generated persona repos (`data/personas/*/repos/*/src/main.py`). Those imports are the only place some skills
   appear (e.g. Celery in `cv-rank-api`), so retrieval evaluation would have silently changed. Caught by reviewing the
   staged diff; fixed by excluding `data/` from ruff, regenerating the corpus, and adding
   `test_implied_skills_survive_in_repo_code`.
