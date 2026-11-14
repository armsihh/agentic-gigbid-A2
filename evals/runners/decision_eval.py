"""Decision evaluation (B4): bid-or-skip F1, scam precision/recall, injection detection, price inside the fair band.

Runs the real Risk Assessor, Fit Matcher (Portfolio MCP + retrieval variant), decision rules and Pricing on dev jobs.
No LLM is involved in these nodes, so this is cheap and exactly reproducible.

    uv run python -m evals.runners.decision_eval --per-persona 120 --variant v2_hybrid
"""
from __future__ import annotations

import argparse
import asyncio
import json
import time
from collections import Counter

from evals.harness import RESULTS, ROOT, deps, load_jsonl, reset_gigsim

PERSONAS = ["ai_ml", "web_dev", "data_analysis"]


def prf(tp: int, fp: int, fn: int) -> dict:
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    return {"precision": round(p, 3), "recall": round(r, 3), "f1": round(2 * p * r / (p + r), 3) if p + r else 0.0,
            "tp": tp, "fp": fp, "fn": fn}


async def run(split: str, per_persona: int, variant: str | None) -> dict:
    from agent.nodes.decision import decide
    from agent.nodes.fit_matcher import make_fit_node
    from agent.nodes.pricing import quote
    from agent.nodes.risk_assessor import assess

    reset_gigsim()
    labels = load_jsonl(ROOT / "evals" / "datasets" / split / "labels.jsonl")
    jobs = {j["job_id"]: j for j in load_jsonl(ROOT / "data" / "gigsim_seed" / "jobs.jsonl")}
    clients = {c["client_id"]: c for c in load_jsonl(ROOT / "data" / "gigsim_seed" / "clients.jsonl")}
    stats = json.loads((ROOT / "data" / "gigsim_seed" / "market_stats.json").read_text())
    rows, t0 = [], time.time()
    for persona in PERSONAS:
        d = deps(persona, variant)
        fit_node = make_fit_node(d)
        pl = [r for r in labels if r["persona"] == persona]
        # stratified: keep every scam/injection/dupe + all gold-bid rows first, then fill with the rest
        pl.sort(key=lambda r: (not (r["bid"] or r["is_scam"] or r["has_injection"]), r["job_id"]))
        for r in pl[:per_persona]:
            job = dict(jobs[r["job_id"]], duplicate_of=r["duplicate_of"])
            client = clients.get(job["client_id"], {})
            risk = assess(job, client, job["duplicate_of"])
            fit = (await fit_node({"job": job}))["fit_report"]
            dec = decide(job, risk.model_dump(), fit, d.profile)
            band = r["fair_price"]
            q = quote(job, client, stats["by_category"].get(job["category"], {}), d.profile, fit["score"],
                      int(job.get("connects_cost") or 0))
            rows.append({"job_id": r["job_id"], "persona": persona, "gold_bid": r["bid"], "pred_bid": dec.action == "bid",
                         "pred_action": dec.action, "gold_scam": r["is_scam"],
                         "pred_scam": any(f.type in ("free_work", "off_platform", "upfront_payment", "pii_request",
                                                     "account_sharing") and f.severity == "high" for f in risk.flags),
                         "gold_injection": r["has_injection"], "pred_injection": risk.injection_detected,
                         "price": q.amount, "band": [band["low"], band["high"]],
                         "price_in_band": band["low"] <= q.amount <= band["high"] * 1.0001,
                         "skip_reasons_gold": r["skip_reasons"], "reasons_pred": dec.reasons[:3], "fit": fit["score"]})
    def metrics(rs):
        bid = prf(sum(x["gold_bid"] and x["pred_bid"] for x in rs), sum(not x["gold_bid"] and x["pred_bid"] for x in rs),
                  sum(x["gold_bid"] and not x["pred_bid"] for x in rs))
        scam = prf(sum(x["gold_scam"] and x["pred_scam"] for x in rs), sum(not x["gold_scam"] and x["pred_scam"] for x in rs),
                   sum(x["gold_scam"] and not x["pred_scam"] for x in rs))
        inj = prf(sum(x["gold_injection"] and x["pred_injection"] for x in rs),
                  sum(not x["gold_injection"] and x["pred_injection"] for x in rs),
                  sum(x["gold_injection"] and not x["pred_injection"] for x in rs))
        priced = [x for x in rs if x["gold_bid"] and x["pred_bid"]]
        return {"n": len(rs), "bid": bid, "scam": scam, "injection": inj,
                "price_in_fair_band": round(sum(x["price_in_band"] for x in priced) / len(priced), 3) if priced else None,
                "accuracy": round(sum(x["gold_bid"] == x["pred_bid"] for x in rs) / len(rs), 3)}
    errors = Counter(("FN " if r["gold_bid"] else "FP ") + (r["reasons_pred"][0].split(" ")[0] if r["reasons_pred"] else "?")
                     for r in rows if r["gold_bid"] != r["pred_bid"])
    return {"split": split, "variant": variant or "config", "per_persona": per_persona, "seconds": round(time.time() - t0),
            "overall": metrics(rows), "by_persona": {p: metrics([r for r in rows if r["persona"] == p]) for p in PERSONAS},
            "error_buckets": dict(errors.most_common(10)), "rows": rows}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="dev")
    ap.add_argument("--per-persona", type=int, default=120)
    ap.add_argument("--variant", default="v2_hybrid")
    a = ap.parse_args()
    res = asyncio.run(run(a.split, a.per_persona, a.variant))
    RESULTS.mkdir(parents=True, exist_ok=True)
    out = RESULTS / f"decision_{a.split}_{res['variant']}.json"
    out.write_text(json.dumps(res, indent=2), encoding="utf-8")
    o = res["overall"]
    print(f"n={o['n']} bid F1={o['bid']['f1']} (P {o['bid']['precision']} R {o['bid']['recall']}) acc={o['accuracy']} "
          f"| scam P={o['scam']['precision']} R={o['scam']['recall']} | injection R={o['injection']['recall']} "
          f"| price in band={o['price_in_fair_band']} | {res['seconds']}s")
    for p, m in res["by_persona"].items():
        print(f"  {p}: bid F1 {m['bid']['f1']} acc {m['accuracy']}")
    print("errors:", res["error_buckets"])
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
