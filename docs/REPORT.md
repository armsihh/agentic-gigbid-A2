# GigBid: R&D Report

AI-4016 Assignment 2 · individual · live: https://gigbid-2ac2.onrender.com · repo: github.com/armsihh/agentic-gigbid-A2

Every number in this report is read from a file in `evals/results/` (named in brackets) or from a commit. Dev = 736
labelled jobs x 3 personas; holdout = 261 jobs, used once per decision, never for tuning.

## 1. Problem and constraints

A freelancer loses hours scanning feeds, spends paid Connects on jobs they will not win, sends generic proposals,
and meets scams asking for free work or off-platform payment. GigBid automates discovery, assessment and drafting; the
human keeps every decision that has an external effect.

**Never automated:** sending a proposal or message, spending Connects, moving a conversation off-platform, claiming
experience the portfolio does not prove. Enforced in code, not in prompts: no LLM node holds a write tool; the only
writer is a deterministic `executor` node that runs after a LangGraph `interrupt()` is resumed by the UI.

**Budgets (declared in `agent/config.yaml`):** p95 <= 20 s per job analysed and <= 60 s per proposal on a laptop;
<= $0.002 per job analysed, <= $0.01 per proposal; <= 30 steps and <= 30k tokens per thread (raised from 12k by
measurement, section 8). Deployment constraint: Render free tier (512 MB, 0.1 CPU) and Groq's free tier
(200k tokens/day per model).

**Data.** GigSim was not provided; following the instructor's update I built it from two Kaggle Upwork datasets
(103,405 cleaned jobs) plus labelled synthetic personas, scams, injected posts and reposts (`docs/DATA_CARD.md`,
ADR 0001). Gold labels are rule-derived from skill overlap; that limits how much any absolute number means and is
stated wherever it matters.

## 2. Architecture

Two hand-written LangGraph graphs (diagrams rendered from code in `docs/ARCHITECTURE.md`):

- **Bid graph** (thread per job): `ingest -> [Job Analyst | Risk Assessor | Fit Matcher]` in parallel via `Send` ->
  `decide` (bid / watch / skip with reasons) -> `pricing` -> `writer` -> `verify` (claim verification) -> `critic`
  (sends back at most twice) -> `compliance` (can block) -> `preview` (marketplace dry run) -> `approval`
  (`interrupt()`) -> `submit`.
- **Conversation graph** (thread per client): `load -> intent (rule override for scam signals) -> slots -> reply ->
  compliance -> preview -> approval -> send`.

**Why each agent exists.** LLMs only where language judgement is needed (Analyst, Writer, Critic, Liaison, intent);
everything that decides money, safety or platform rules is deterministic and configured (ADR 0002). That is why a
job analysis costs fractions of a cent and every skip has a quoted reason.

**Marketplace port.** One `MarketplacePort` with GigSim (REST) and live Upwork (official MCP, Streamable HTTP,
OAuth 2.1, tokens encrypted per user) adapters; switching is `MARKETPLACE_MODE`. Upwork submit never auto-confirms.

**MCP surface.** Three own servers (Portfolio read-only, Marketplace read/write with idempotency keys, dry_run, bearer
scopes, per-user rate limiter, append-only PII-masked audit log; Workspace calendar + email drafts) plus the official
Upwork and GitHub servers (`docs/TOOLS.md`, generated from the schema snapshots CI checks). Agents get tools by
allowlist; a client interceptor adds timeouts, bounded retries and degraded-mode detection.

**Stores.** Graph state is checkpointed per node (Postgres/Neon in production, SQLite locally). Execution trace = a
`trace` channel of step summaries + MCP audit logs under one trace id. Long-term memory = LangGraph store written
only through promotion rules: style rules need the same edit in 3 distinct threads with no contradiction; outcome
insights need >= 10 outcomes per arm and disjoint Wilson 90% intervals (`agent/memory/promotion_rules.py`).

## 3. R&D question A: tool granularity

**Hypothesis.** A few coarse tools save prompt tokens but cost selection accuracy; well-described task-level tools
are the best trade-off.

**Setup.** 24 tasks with known correct calls (`evals/datasets/tool_tasks.json`), one open model
(`qwen/qwen3.8-27b`) choosing one call per task, three tool sets: fine (27 narrow tools), coarse (2 tools:
`marketplace(action, params)`, `portfolio(action, params)`), ours (13 real MCP tools with their shipped
descriptions) [tool_design.json].

| Tool set | Tools | Selection accuracy | Argument accuracy | Tokens / task | Tasks |
|---|---|---|---|---|---|
| Fine | 27 | 0.88* | 0.83* | not measured | 24* |
| Coarse | 2 | 0.29 | 0.29 | 448 | 24 |
| Ours | 13 | **0.92** | **0.88** | 2,316 | 24 |

\* Fine: an earlier complete run on `gpt-oss-20b` (lost to a rate-limit crash before it saved; the runner now saves
after every task). The rerun on `qwen/qwen3.8-27b` hit the free tier's daily cap before the fine set started, so fine is
on a different model and has no token count; treat that row as indicative.

**Conclusion.** The hypothesis holds. Our 13 task-level tools picked the right tool on 22/24 tasks and
filled the arguments correctly on 21/24; it called the wrong tool twice (`list_skills` for `get_client_history`, `search_evidence` for `get_job`). The 2-tool coarse set was
5x cheaper per call (448 vs 2,316 tokens) but right only 29% of the time: hiding the operation inside an
`action` string made the model guess action names and parameter shapes, so fewer tools did not mean easier
choices. Fine-grained tools were about as accurate as ours in the earlier run but send twice as many schemas on
every call. Task-level tools with precise descriptions are the best trade-off.

## 4. R&D question B: retrieval, verification, and what shipped

**Hypothesis (stated before running).** "Requirement decomposition plus hybrid retrieval raises evidence Recall@5
by at least 10 points over V0 on jobs with four or more requirements."

**Results** [rag_retrieval_dev.json], 460 dev jobs with gold evidence, project-level metrics:

| Variant | Recall@5 | MRR | nDCG@10 | p95 s |
|---|---|---|---|---|
| V0 naive dense (fixed chunks) | 0.593 | 0.676 | 0.578 | 0.10 |
| V1 requirement decomposition | 0.560 | 0.656 | 0.563 | 0.11 |
| V2 hybrid BM25 + dense (RRF) | 0.617 | 0.686 | 0.617 | 0.24 |
| V3 + cross-encoder rerank | 0.630 | **0.744** | 0.648 | 0.55 |
| V4 + outcome-aware boost | 0.606 | 0.670 | 0.615 | 0.63 |
| **V5 multi-vector (shipped)** | **0.648** | 0.739 | **0.697** | 0.65 |
| V8 corrective (refuse when weak) | 0.468 | 0.561 | 0.511 | 1.01 |

**The hypothesis was wrong.** Decomposition alone *lowered* recall (0.593 -> 0.560): one query per tag loses the
context that ties "Python" to *this* job, and RRF over many weak lists dilutes the strong one. Hybrid retrieval
recovered it (exact library names), the cross-encoder gave the biggest MRR gain (+0.058), and grouping all vectors of
a project (case study, README, code) gave the best nDCG: repos that look irrelevant from their README are found
through their code (the Celery case, `test_implied_skills_survive_in_repo_code`). The outcome boost (V4) hurt: past
wins correlate with popular projects, not with relevance to the job. V8 refuses 81% of off-profile jobs but also 30%
of jobs that have evidence at threshold 0.5; it needs a tuned threshold before it can ship.

**Ablation of V5:** a remove-one-stage ablation was not run (free-tier time); the variant table isolates each stage cumulatively (V2 = +hybrid, V3 = +rerank, V5 = +grouping).

**Claim verification (B3).** Each experience claim is checked against retrieved evidence with the cross-encoder plus
hard facts: every number and named tool in the claim must appear in the evidence, and "N years" must be literal. A
number not in the evidence makes the claim unsupported however relevant the sentence is (a fix found by the CI smoke
gate: "routed 99% of tickets" survived as "partly supported" when the evidence said 81%). Unsupported claims are
removed before the Critic sees the draft.

| Proposals (real graph) | Unsupported / proposal before -> after | Judge (1-5) | GigSim reply rate | p95 s | USD / proposal |
|---|---|---|---|---|---|
| V0, gpt-oss-120b writer, 5 proposals [proposal_eval_open_gptoss120b_partial.json] | 0.2 -> 0.0 | 3.0 | 0.20 | 342 | 0.0043 |
| V0, tiered gpt-oss-120b writer, 5 proposals [proposal_eval_open.json] | 1.0 -> 0.0 | 3.0 | 0.00 | 203 | 0.0027 |
| V5, same jobs and models, 5 proposals [proposal_eval_open.json] | **0.2** -> 0.0 | **3.2** | 0.00 | 639 | 0.0025 |

**Judge calibration.** 30 proposals labelled by me before seeing the judge; Cohen's kappa 0.392 (quadratic-weighted
0.717), exact agreement 0.53, within one point 0.87; the judge is about 0.2 points more generous (2.77 vs 2.57)
[judge_calibration.json]. So judge scores are trustworthy for ranking variants, not as absolute grades; its biggest
misses reward concrete metrics in a proposal that does not answer the job.

**Shipped.** V5 locally and in compose; **V2 on the public host** because V5 needs ~480 MB and ~1 s/search on a
laptop (~10 s at 0.1 CPU) while V2 needs 291 MB and 0.1 s; production gives up 0.031 Recall@5 (ADR 0004).
For the same reason the public host scores claim relevance with the bi-encoder the index already loaded instead of
the cross-encoder: loading the cross-encoder at `verify` added ~103-137 MB and the host was OOM-killed on every
proposal (found live, reproduced locally, `VERIFIER_RELEVANCE=embedding`). Calibrated on 106 claim/evidence pairs it
agrees with the cross-encoder on 92.5% of labels and still rejects 98% of claims against unrelated evidence; number
and tool checks are lexical in both, so a wrong number is always removed. Where
better retrieval did not translate into a better reply rate: on the same six jobs V5 cut unsupported claims in
the first draft five-fold (1.0 -> 0.2 per proposal; verification removes the rest either way) and the judge scored it
slightly higher (3.2 vs 3.0), but simulated reply rate was 0 for both: five proposals per arm is far too few to see
GigSim's outcome differences, and the Critic asked V5 for more revisions (1.8 vs 0.4), which, with free-tier
rate-limit waits, tripled p95 latency. Better evidence buys honesty in the first draft, not measurable replies at n=5.

## 5. R&D question C: single agent vs supervisor vs graph

Same jobs (2 bid-worthy, 1 scam, 1 injected post), same model, three designs: one ReAct agent holding all read tools,
`langgraph-supervisor` over three ReAct sub-agents, and our graph [architecture_comparison.json].

**Not completed: free-tier daily caps.** The planned 4 jobs x 3 designs did not fit Groq's 200k tokens/model/day
alongside the proposal evaluation; I stopped it after the first design on the first job rather than spend the quota
the live demo needs. What was measured, on the same bid-worthy job (`job-01ce9333d8`) and model family:

| Design | Outcome | Tokens | Unsupported claims | Violations |
|---|---|---|---|---|
| Single ReAct (all read tools) | no answer: hit the daily cap mid-run | 15,080 (and counting) | n/a | n/a |
| Supervisor | not run | - | - | - |
| Our graph (V5, proposal eval) [proposal_eval_open.json] | verified draft waiting for approval, judge 3/5, 336 s | 11,327 | 0 before and after verification | 0 |

This is one job, so it is indicative, not a result. What it shows is consistent with the design argument: the single
agent spent more tokens without reaching an answer (in an earlier attempt it also called a tool that does not exist,
`job`, which Groq rejected), while the graph's deterministic nodes (risk, decision, pricing, compliance) cost zero tokens and
its LLM calls are bounded per node. On scams and injected posts the gap is structural, not statistical: our graph skips
them before any LLM call (0.4 s, zero tokens; 72/72 scams and 45/45 injections in section 2), whereas a ReAct agent
has to read the injected text to decide. Where (a) would plausibly win: open-ended, one-off questions the graph has no
node for ("which of my repos fits this?"), where its flexibility beats a fixed pipeline. The runner
(`evals/runners/architecture_eval.py`) is complete and resumable; with a paid tier it is a ~1-hour run.

## 6. The change request

The announced 2 November policy update was never released, so I wrote one with a new **cost** (+4 Connects on jobs
with 50+ applicants) and a new **rule** (cover letters <= 1,500 characters), applied it on the platform side, and
measured the cost of absorbing it (`docs/CHANGE_REQUEST.md`, `tests/integration/test_change_request.py`).
**GigBid: 12 lines in 5 files plus one config value, about 25 minutes. Pricing: zero changes**, because it already
prices with the marketplace's per-job Connects cost. The real cost was one rule hard-coded in three places (writer
prompt, critic, nothing in compliance); every platform rule a node depends on now lives in config.

## 7. Signature extension: X1 agency mode

The three personas act as one agency; GigBid routes each job to the best-fit member (Fit Matcher per member against
that member's portfolio, same bar as a bid decision) or to nobody (`docs/EXTENSION.md`) [agency_routing.json].
On 150 clean dev jobs: **0.773** routing accuracy vs 0.673 routing by category tag and 0.267 random. The tag is better
at *who* (0.91 vs 0.71 when someone should bid); evidence-based routing is far better at *nobody* (0.90 vs 0.20),
which is what saves an agency's Connects.

## 8. Failure analysis

From [failure_analysis.json], decision_dev and the proposal runs:

| Category | Count | Example | Fix tried | Worked? |
|---|---|---|---|---|
| Wrong bid (fit over-estimated) | 35 (338 before fix) | "AWS Developer" for the AI/ML persona: fit 0.70, gold 0.20 | past proposals excluded as fit proof (they carry the *client's* skill tags); generic words ("development", "data") no longer earn partial credit | Yes: dev precision 0.39 -> 0.83; holdout F1 0.51 -> 0.76 |
| Missed evidence | 98 | "AI based website": ours 0.0, gold 0.5 (Browser Extension, Web Application not found) | k 4 -> 6 per requirement | Partly: recall 0.58 -> 0.62 |
| Wrong skip (risk) | 6 | "Senior Java Developer": the crypto-payment pattern fired on "Crypto, SSL/TLS, PKI" (also "crypto financial news", "cryptopricepal.com") | proposed: require payment context ("pay ... in crypto/USDT"); not applied after the holdout was locked | Not yet |
| Mispriced | 0 on bid jobs | - | - | - |
| Unsupported claim | 1 in 5 real proposals before verification, 0 after | removed by the verifier | verifier + numeric-fact rule | Yes |
| Wrong number kept | 1 (CI smoke) | "routed 99%" kept as partly supported | numeric facts must appear in evidence | Yes |
| Budget | 40% of real runs at 12k tokens | threads halted as needs_attention before approval | budget set by measurement (30k) | Yes (ADR 0005) |
| Tool error (LLM rate limit) | 25 | Groq 200k tokens/day cap mid-run -> dead letter | runners wait for quota and retry the job | Yes for evals; production shows "needs attention" |
| Malformed tool call | intermittent | gpt-oss-20b emitted unparseable tool JSON (Analyst fell back to tag spec) | retry in JSON-schema mode | Yes |
| Injection / generic opening / compliance miss | 0 observed | 45/45 planted injections detected, 1 false positive in 840 real posts | - | - |

The most important lesson came from the holdout: my first dev evaluation sampled bid-worthy jobs first and reported
F1 0.92; on the full distribution it was 0.51. Fixing the sampling, then the two leaks above on **dev only**, and
checking holdout **once** gave the honest 0.76 [decision_holdout_v2_hybrid.json].

## 9. Safety and platform respect

**Must never happen:** send without approval, spend Connects without approval, leave the platform, claim unproven
experience, follow instructions inside a job post or client message, scrape.
**Enforcement:** write tools only in the executor after `interrupt()`; bearer scopes keep write tools out of reading
agents' tokens; idempotency keys make retries and crash replays safe (tested exactly-once); injection patterns are
stripped and untrusted text is delimited; deterministic Compliance removes contact details and guarantees and blocks
off-platform, free-work, fabricated-years and over-length text, including human edits; PII masked in logs and audit;
OAuth tokens encrypted per user; live Upwork only via the official MCP with a 15-minute minimum search interval.
**What still gets through:** paraphrased or non-English injections with no pattern (layer 2/3 defences remain: no
write tools, approval); scams worded unlike our six templates (detection rates are optimistic); a human who approves
a bad draft.

## 10. Results against declared budgets (hidden test)

The instructor's hidden test runs after submission. On our own holdout (never tuned on): bid F1 0.760 (P 0.883,
R 0.667), scam and injection detection 1.00, price inside the fair band 1.00 [decision_holdout_v2_hybrid.json].
Latency and cost: job analysis without drafting is deterministic + retrieval (< 2 s locally); a full proposal took
p50 94 s / p95 342 s with gpt-oss-120b on Groq's free tier, **over** the 60 s p95 budget, because free-tier rate-limit
waits dominate; cost was $0.0043 per proposal, **within** the $0.01 budget [proposal_eval_open_gptoss120b_partial.json].
The latency budget is met only without rate-limit waits; a paid tier or a second provider is the fix.
