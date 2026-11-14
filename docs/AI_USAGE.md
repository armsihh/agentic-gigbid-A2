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
6. **An evaluation sample that flattered the system.** The first decision evaluation sorted bid-worthy jobs first to
   keep a small sample interesting, and reported bid F1 0.92. On the full holdout it was 0.51. Caught by running the
   holdout; fixed by evaluating the full splits, then fixing two real leaks found by reading false positives.
7. **Past proposals used as proof of skill.** The Fit Matcher counted a skill as covered if any retrieved past proposal
   carried it, but proposals store the *client's* job tags. Fixed by restricting fit evidence to case studies, repos,
   CV and reviews (precision 0.39 -> 0.83 on dev).
8. **A fabricated number survived verification.** "Routed 99% of tickets" (evidence: 81%) was kept as "partly
   supported". Caught by the CI smoke gate; any number missing from the evidence now makes a claim unsupported.
9. **A report example written from memory.** I first described a wrong-skip case as a Skype contact request; checking
   the data showed the crypto-payment pattern firing on "Crypto, SSL/TLS, PKI". Every report example is now pulled
   from `evals/results/failure_analysis.json`.
10. **Results overwritten by a failed run.** A rate-limited evaluation overwrote a file of good results with an empty
    run. Runners now write per-profile files and never overwrite with zero completed proposals.
