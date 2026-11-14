# ADR 0003: Ship V5 multi-vector retrieval (chosen by measurement)

**Status:** accepted · 2026-11-11 · evidence: `evals/results/rag_retrieval_dev.json`

| Variant | Recall@5 | MRR | nDCG@10 | p95 s |
|---|---|---|---|---|
| V0 naive | 0.593 | 0.676 | 0.578 | 0.10 |
| V2 hybrid | 0.617 | 0.686 | 0.617 | 0.24 |
| V3 rerank | 0.630 | 0.744 | 0.648 | 0.55 |
| **V5 multi-vector** | **0.648** | 0.739 | **0.697** | 0.65 |

**Decision.** V5 (hybrid BM25 + dense, cross-encoder rerank, results grouped per project) is the design wherever the
host can afford a cross-encoder: local, docker compose, evaluation. V1 (decomposition alone) and V4 (outcome boost)
lowered recall and are not shipped; V8 (corrective) refuses 81% of off-profile jobs but also 30% of jobs that have
evidence at threshold 0.5, so it needs threshold tuning before use.
