# ADR 0004: The public deployment runs V2 hybrid, not V5

**Status:** accepted · 2026-11-12

**Context.** The public link runs on Render's free tier: 512 MB RAM and 0.1 CPU, one service. Measured locally:
V5 needs ~480 MB with the embedder and cross-encoder loaded and ~1 s per evidence search on a laptop (~10 s at
0.1 CPU; the Fit Matcher makes up to 8 searches per job). V2 hybrid needs 291 MB and ~0.1 s per search.
In a container capped at 512 MB / 0.1 CPU the all-in-one image used 372 MB.

**Decision.** Production sets `RAG_VARIANT=v2_hybrid`; local and compose use V5. One environment variable switches.

**Consequences.** Production gives up 0.031 Recall@5 and 0.080 nDCG@10 versus V5 (`rag_retrieval_dev.json`) to stay
inside memory and the declared latency budget. Bid F1 measured with V2: 0.760 holdout / 0.706 dev (`decision_*_v2_hybrid.json`).
With a paid tier or a hosted open reranker, V5 is the drop-in upgrade.
