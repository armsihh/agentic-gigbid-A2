# Résumé bullet (numbers from evals/results/)

- Built GigBid, a multi-agent LangGraph freelancing copilot with 3 MCP servers, human-in-the-loop approval and
  crash-safe exactly-once submission; raised holdout bid/skip F1 from 0.51 to 0.76 by error analysis and caught
  100% of 72 planted scams and 45 prompt injections at zero LLM cost.
- Benchmarked 7 RAG variants on 460 labelled jobs: shipped hybrid + cross-encoder + multi-vector retrieval
  (nDCG@10 0.578 -> 0.697) and claim verification that removes unsupported claims before review; deployed on
  Docker/Render + Neon with CI eval gates and 5 Playwright flows.

Sources: decision_holdout_v2_hybrid.json, decision_dev_v2_hybrid.json, rag_retrieval_dev.json, proposal_eval_*.json.
