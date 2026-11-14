# ADR 0001: Build our own GigSim from Kaggle data

**Status:** accepted · 2026-11-10

**Context.** The assignment describes GigSim as provided, but the starter kit did not include it, and the
instructor's follow-up said to use Kaggle Upwork datasets and synthetic data where real data is missing.

**Decision.** Build GigSim (`gigsim/`) as a separate FastAPI service with a documented contract (`gigsim/API.md`):
real job posts (Kaggle, 2023/2024) plus synthetic scams, prompt-injection posts, reposts, personas and client
preferences. Nothing in GigBid imports `gigsim.*`; only the marketplace adapter speaks its HTTP API. The simulator is
frozen by a checksum manifest checked in CI.

**Consequences.** We control determinism (outcomes seeded by proposal content) and fault injection, and an official
GigSim can replace ours by changing one adapter. Risk: our client model rewards what we designed it to reward, so reply
rates measure "fit to this simulator", which the report states.
