"""Failure analysis (report section 8): failed dev jobs grouped into the assignment's taxonomy, from the result files.

Taxonomy: missed evidence, wrong skip, wrong bid, mispriced, unsupported claim, generic opening, compliance miss,
injection, tool error, budget. Writes evals/results/failure_analysis.json (examples + counts).

    uv run python -m evals.runners.failure_analysis
"""
from __future__ import annotations

import json
from collections import Counter

from evals.harness import RESULTS, ROOT, load_jsonl


def main() -> None:
    jobs = {j["job_id"]: j for j in load_jsonl(ROOT / "data" / "gigsim_seed" / "jobs.jsonl")}
    labels = {(r["job_id"], r["persona"]): r for r in load_jsonl(ROOT / "evals" / "datasets" / "dev" / "labels.jsonl")}
    dec = json.loads((RESULTS / "decision_dev_v2_hybrid.json").read_text())
    out = []
    for r in dec["rows"]:
        mispriced = r["gold_bid"] and r["pred_bid"] and not r["price_in_band"]   # price only matters on a bid
        if r["gold_bid"] == r["pred_bid"] and not mispriced:
            continue
        g = labels[(r["job_id"], r["persona"])]
        j = jobs[r["job_id"]]
        reason = (r["reasons_pred"] or ["?"])[0]
        if r["gold_bid"] and not r["pred_bid"]:
            cat = "wrong skip (risk)" if reason.startswith("risk") else (
                "missed evidence" if "fit" in reason or "evidence" in reason else "wrong skip (other)")
        elif r["pred_bid"] and not r["gold_bid"]:
            cat = "wrong bid (fit over-estimated)"
        else:
            cat = "mispriced"
        out.append({"category": cat, "persona": r["persona"], "job_id": r["job_id"], "title": j["title"][:90],
                    "job_skills": j["skills"][:6], "our_fit": r["fit"], "gold_fit": g["fit_score"],
                    "gold_evidence": g["gold_evidence_projects"][:3], "our_reason": reason,
                    "gold_skip_reasons": g["skip_reasons"]})
    # proposal-level failures from the real-LLM runs
    for f in ("proposal_eval_open_gptoss120b_partial.json", "proposal_eval_open_eval.json"):
        p = RESULTS / f
        if not p.exists():
            continue
        d = json.loads(p.read_text())
        for variant, rows in d.get("rows", {}).items():
            for row in rows:
                errs = " ".join(row.get("errors", [])) + " " + str(row.get("error", ""))
                if row.get("halt") == "needs_attention":
                    out.append({"category": "budget (token budget too small)", "source": f, "variant": variant,
                                "job_id": row["job_id"], "detail": "thread halted before approval: >12k tokens"})
                elif "429" in errs:
                    out.append({"category": "tool error (LLM rate limit)", "source": f, "variant": variant,
                                "job_id": row["job_id"], "detail": errs[:160]})
                elif row.get("unsupported_before"):
                    out.append({"category": "unsupported claim (caught by verifier)", "source": f, "variant": variant,
                                "job_id": row["job_id"], "detail": f"{row['unsupported_before']} removed before critic"})
    counts = Counter(o["category"] for o in out)
    res = {"counts": dict(counts.most_common()),
           "examples": {c: [o for o in out if o["category"] == c][:4] for c in counts}}
    (RESULTS / "failure_analysis.json").write_text(json.dumps(res, indent=2), encoding="utf-8")
    print(json.dumps(res["counts"], indent=1))


if __name__ == "__main__":
    main()
