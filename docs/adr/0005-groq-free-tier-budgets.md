# ADR 0005: Open models on Groq's free tier; budgets set by measurement

**Status:** accepted · 2026-11-14

**Context.** The open profile uses `openai/gpt-oss-20b` (small nodes) and `openai/gpt-oss-120b` (writer, critic,
liaison) on Groq, with `qwen/qwen3.8-27b` as fallback. Groq's free tier allows 8,000 tokens/minute and 200,000
tokens/day per model. A real bid-graph run measured ~11k tokens without revisions and up to ~25k with two Critic loops.

**Decisions.**
1. Token budget per job raised from 12,000 to 30,000: with 12k, 40% of real runs halted as `needs_attention`
   before reaching approval (`evals/results/proposal_eval_open_gptoss120b_partial.json`).
2. Evaluations that need many LLM calls use the `open_eval` profile (qwen writer, gpt-oss-20b judge) and small samples,
   so the 120b daily quota stays available for the live demo.
3. Structured output falls back to JSON-schema mode when a small model emits a malformed tool call.

**Consequences.** Sample sizes for LLM-graded results are small and reported as such; the deterministic metrics (retrieval,
decisions, scams, injections, routing) use the full dev set.
