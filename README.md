# GigBid: a multi-agent freelancer copilot

GigBid finds freelance jobs, checks them for scams and prompt injections, decides whether they are worth the Connects,
writes proposals in which **every claim is backed by real portfolio evidence**, and handles client replies.
**Nothing is sent until a human approves it.**

**Live:** https://gigbid-2ac2.onrender.com (reviewer login in the Classroom submission) ·
**Demo video:** _link in submission_ · **Write-up:** _link in submission_ · AI-4016 Assignment 2, individual.

<!-- demo GIF: docs/images/demo.gif -->

## How it works
```
 React UI --SSE/REST--> FastAPI --> LangGraph bid graph (one thread per job)
                                    ingest -> [Job Analyst | Risk Assessor | Fit Matcher]  (parallel)
                                    -> decide (bid / watch / skip, with reasons) -> Pricing
                                    -> Writer -> claim verification -> Critic (<= 2 revisions)
                                    -> Compliance -> dry-run preview -> YOUR APPROVAL (interrupt) -> submit
                                 --> conversation graph (one thread per client): intent -> slots -> reply -> approval
 Tools only via MCP: Marketplace (GigSim | official Upwork MCP behind one port) · Portfolio (RAG) · Workspace
```
Diagrams rendered from code, why each agent exists, state vs trace vs memory: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).
Tools: [docs/TOOLS.md](docs/TOOLS.md) · Data: [docs/DATA_CARD.md](docs/DATA_CARD.md) ·
Operations: [docs/RUNBOOK.md](docs/RUNBOOK.md) · Decisions: [docs/adr/](docs/adr/) · Extension: [docs/EXTENSION.md](docs/EXTENSION.md).

## Results
Every number below is read from a file in [`evals/results/`](evals/results/). Dev set = `evals/datasets/dev`
(736 jobs x 3 personas); the holdout split is never used for tuning.

**Retrieval (R&D B)** - 460 dev jobs with gold evidence ([rag_retrieval_dev.json](evals/results/rag_retrieval_dev.json))

| Variant | Evidence Recall@5 | MRR | nDCG@10 | p95 latency (s) |
|---|---|---|---|---|
| V0 naive dense | 0.593 | 0.676 | 0.578 | 0.10 |
| V1 requirement decomposition | 0.560 | 0.656 | 0.563 | 0.11 |
| V2 hybrid BM25 + dense (RRF) | 0.617 | 0.686 | 0.617 | 0.24 |
| V3 + cross-encoder rerank | 0.630 | **0.744** | 0.648 | 0.55 |
| V4 + outcome-aware boost | 0.606 | 0.670 | 0.615 | 0.63 |
| **V5 multi-vector (shipped)** | **0.648** | 0.739 | **0.697** | 0.65 |
| V8 corrective (refuse when weak) | 0.468 | 0.561 | 0.511 | 1.01 |

Shipped: V5 locally / compose; V2 on the 512 MB public host ([ADR 0004](docs/adr/0004-production-rag-variant.md)).
Negative results: decomposition alone and the outcome boost both *lowered* recall.

**Proposals (B4/B5, R&D B)** - real bid graph on the same 6 jobs per variant, tiered open models (gpt-oss-120b writer,
Gemma 4 / Nemotron fallbacks) ([proposal_eval_open.json](evals/results/proposal_eval_open.json)):

| Variant | Unsupported claims / proposal (before -> after verification) | Judge (1-5) | GigSim reply rate | p95 latency (s) | Cost / proposal (USD) |
|---|---|---|---|---|---|
| V0 naive | 1.0 -> 0.0 | 3.0 | 0.00 | 203 | 0.0027 |
| V5 shipped | 0.2 -> 0.0 | 3.2 | 0.00 | 639 | 0.0025 |

Five proposals per arm: enough to see V5 cut fabricated claims in first drafts five-fold, far too few for reply
rates. Judge calibrated against 30 hand labels: kappa 0.39, quadratic 0.72, within one point 0.87.

**Decisions** - full splits, production retrieval V2 ([dev](evals/results/decision_dev_v2_hybrid.json),
[holdout](evals/results/decision_holdout_v2_hybrid.json))

| Split | Rows | Bid-or-skip F1 | Precision | Recall | Accuracy | Scam P / R | Injection recall | Price in fair band |
|---|---|---|---|---|---|---|---|---|
| Dev | 2,208 | 0.706 | 0.827 | 0.616 | 0.937 | 1.00 / 1.00 | 1.00 | 1.00 |
| **Holdout** | 783 | **0.760** | 0.883 | 0.667 | 0.945 | 1.00 / 1.00 | 1.00 | 1.00 |

An earlier stratified dev sample reported F1 0.92; on the full holdout it was 0.51. Two leaks found by reading false
bids (past proposals used as proof; generic words earning partial credit) were fixed on dev only, then holdout was run
once (report section 8).

**Agency routing (extension X1)** - 150 dev jobs ([agency_routing.json](evals/results/agency_routing.json)):
0.773 accuracy vs 0.673 routing by category tag and 0.267 random; 0.90 vs 0.20 at saying "nobody should bid".

**Change request** - a new Connects surcharge and a 1,500-character rule absorbed with 12 lines in 5 files and one
config value; pricing needed no change ([docs/CHANGE_REQUEST.md](docs/CHANGE_REQUEST.md)).

Report: [docs/REPORT.pdf](docs/REPORT.pdf) · Write-up draft: [docs/WRITEUP.md](docs/WRITEUP.md) ·
Portfolio MCP server (install with `uvx`): [mcp_servers/portfolio/README.md](mcp_servers/portfolio/README.md).

**Tool granularity (R&D A)** - 24 tasks, `qwen3.8-27b` ([tool_design.json](evals/results/tool_design.json)): partial,
the night before submission every free Groq model was at its daily cap. Our 13 task-level tools: right tool on 0.83
of the tasks finished; an earlier unsaved run had the 2-tool coarse set at 0.25. Details and caveats: report section 3.

## Run it
```bash
cp .env.example .env              # add GROQ_API_KEY (free), REVIEWER_PASSWORD
docker compose -f infra/docker-compose.yml up --build      # http://localhost:8080
```
Without Docker: `uv sync`, `make gigsim`, `make api`, then `cd apps/web && npm i && npm run dev`.
Tests: `make test` (72 Python tests) · `cd apps/web && npx playwright test` (5 UI flows) ·
`uv run python -m evals.runners.smoke_gate` (the CI eval gate).
Reproduce results: `uv run python -m evals.runners.rag_eval`, `... decision_eval`, `... proposal_eval`,
`... tool_design_eval`, `... agency_eval`.

## Stack (pinned in `uv.lock`, `apps/web/package-lock.json`)
Python 3.12 · LangGraph 1.2 · langchain-mcp-adapters · MCP Python SDK 1.30 · FastAPI · SQLAlchemy · Postgres (Neon) /
SQLite · Arq + Redis · fastembed (bge-small-en-v1.5, ms-marco-MiniLM-L-6-v2 cross-encoder, ONNX on CPU) · rank-bm25 ·
React 18 + Vite + TypeScript, client generated with openapi-typescript · Playwright · Groq (gpt-oss-20b/120b,
qwen3.8-27b, open-weight) · Docker, Render.

## Safety
Job posts and client messages are untrusted: injection patterns are stripped, text is delimited, no LLM node holds a
write tool, every send needs approval, compliance re-checks human edits, PII is masked in logs and audit records,
OAuth tokens are encrypted per user. Details and known gaps: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md),
[docs/RUNBOOK.md](docs/RUNBOOK.md).
