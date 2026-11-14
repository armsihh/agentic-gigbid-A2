# ADR 0002: Deterministic risk, decision, pricing and compliance; LLMs only for language

**Status:** accepted · 2026-11-11

**Context.** Risk, bid/skip, price and policy decide money, safety and platform standing. LLM judgement there is
slower, costs tokens on every job, can be jailbroken by the post it is judging, and is hard to explain in a viva.

**Decision.** Risk Assessor, decision, Pricing Strategist, Compliance Guard, Scout and Executor are deterministic and
read their rules from `agent/config.yaml`. LLMs are used for the Job Analyst, Writer, Critic, intent and Client
Liaison. No LLM node holds a write tool.

**Consequences.** Scam detection P/R 1.0 on dev and holdout at zero token cost (optimistic: template scams); bid F1
0.760 on the full holdout (0.706 dev); a prompt injection cannot move money because no model can. The change request becomes a config
edit. Cost: rule-based detection misses paraphrased attacks it has no pattern for (documented in the report).
