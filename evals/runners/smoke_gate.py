"""CI smoke eval with failure thresholds (E2). No API keys needed: every metric here is LLM-free.

  - retrieval: Recall@5 of the shipped variant on 30 dev jobs (10 per persona)
  - decisions: bid-or-skip F1 + scam recall on 30 dev jobs
  - grounding: the claim verifier must remove fabricated claims from fixed adversarial drafts
Fails (exit 1) if a metric drops below its threshold in evals/thresholds.json. Writes evals/results/smoke_gate.json.
"""
from __future__ import annotations

import asyncio
import json
import sys

from evals.harness import RESULTS, ROOT, load_jsonl

THRESH = json.loads((ROOT / "evals" / "thresholds.json").read_text())

FABRICATED = [
    ("I have 10 years of experience running Kubernetes clusters for Google.", True),
    ("I built a ticket classifier that routed 99% of tickets automatically.", True),
    ("I fine-tuned a DistilBERT classifier on 38k historical tickets for a UK SaaS helpdesk company.", False),
]
EVIDENCE = ("Support ticket triage classifier. Fine-tuned a DistilBERT classifier on 38k historical tickets for a UK "
            "SaaS helpdesk company. Routed 81% of tickets automatically at 94% precision.")


def retrieval() -> float:
    from evals.runners.rag_eval import evaluate
    from rag.ingest.loaders import load_corpus
    labels = load_jsonl(ROOT / "evals" / "datasets" / "dev" / "labels.jsonl")
    jobs = {j["job_id"]: j for j in load_jsonl(ROOT / "data" / "gigsim_seed" / "jobs.jsonl")}
    variant = THRESH.get("smoke_variant", "v2_hybrid")
    r = evaluate(variant, labels, jobs, load_corpus(ROOT / "data" / "personas"), limit=10)
    return r["overall"]["recall@5"]


def decisions() -> dict:
    from evals.runners.decision_eval import run
    res = asyncio.run(run("dev", 10, THRESH.get("smoke_variant", "v2_hybrid")))
    return {"bid_f1": res["overall"]["bid"]["f1"], "scam_recall": res["overall"]["scam"]["recall"]}


def grounding() -> float:
    from evals.harness import default_verifier
    from rag.verify import Evidence
    v = default_verifier()
    ev = [Evidence(evidence_id="e1", text=EVIDENCE)]
    caught = sum((v.check(c, ev).label == "unsupported") == fabricated for c, fabricated in FABRICATED)
    return caught / len(FABRICATED)


def main() -> None:
    got = {"recall@5": retrieval(), **decisions(), "verifier_accuracy": grounding()}
    fails = [f"{k} {got[k]:.3f} < {THRESH[k]}" for k in THRESH if k in got and got[k] < THRESH[k]]
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "smoke_gate.json").write_text(json.dumps({"metrics": got, "thresholds": THRESH, "failures": fails}, indent=2))
    print(json.dumps(got, indent=1))
    if fails:
        print("SMOKE EVAL FAILED:\n  " + "\n  ".join(fails))
        sys.exit(1)
    print("smoke eval passed")


if __name__ == "__main__":
    main()
