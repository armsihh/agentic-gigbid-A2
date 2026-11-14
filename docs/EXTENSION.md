# Signature extension: X1 Agency mode

**What it does.** The three personas (AI/ML engineer, full-stack developer, data analyst) work as one agency with a
shared inbox. For each job, GigBid decides **which member should bid**, or that **nobody should**, and the bid graph
then drafts in that member's voice: their profile, rates, portfolio evidence and learned style memory.

**How it works** (`agent/nodes/agency.py`). The Fit Matcher runs once per member against that member's
portfolio only (tenant-scoped Portfolio MCP identity `user@member`). Members are ranked by (rate acceptable, fit
score, requirements covered). The best member is chosen only if their fit reaches the same bar a "bid" decision
needs (`decision.watch_if_fit_below`, 0.55) at an acceptable rate; otherwise the job is routed to nobody, with the
reason recorded. No LLM call: routing costs nothing and is reproducible.

**How it was measured** (`evals/runners/agency_eval.py` -> `evals/results/agency_routing.json`).
150 clean dev jobs (no scams, injections or reposts): 100 where at least one member's gold label is `bid`,
50 where nobody's is. A routing is correct if it picks any member whose gold label is `bid`, or picks nobody when
no member should bid. Baselines: route by the job's category tag (what a human dispatcher does) and random.

| Router | Overall accuracy | When someone should bid | When nobody should bid |
|---|---|---|---|
| **GigBid (fit-based)** | **0.753** | 0.870 | **0.520** |
| Category tag | 0.673 | **0.910** | 0.200 |
| Random member | 0.267 | 0.400 | 0.000 |

**What it shows.** The category tag is a strong signal for *who* (0.91), but it cannot say *nobody*: it sends every
in-category job to someone, including jobs no member can prove they can do. Evidence-based routing gives up 4 points on
"who" and gains 32 points on "nobody", which is what saves Connects in an agency. An earlier version used only the skip
threshold (0.40) and routed almost everything (0.08 on "nobody"); using the bid-level bar fixed that, measured on dev.

**Limits.** Gold labels are rule-derived from skill overlap (see DATA_CARD), the same family of signal the router uses,
so absolute numbers are optimistic; the comparison with the category baseline is the meaningful part.
