"""Extension X1 (agency mode) evaluation: does GigBid route each job to the right team member?

Gold: a job's correct member is the persona whose gold label says `bid` (if several, any of them is correct;
if none, the right answer is "no member"). Compared with two baselines:
  category  route by the job's marketplace category (what a human dispatcher would do from the tag)
  random    uniform random member
Metrics: routing accuracy, accuracy on jobs where someone should bid, and "no member" precision.

    uv run python -m evals.runners.agency_eval --jobs 150
"""
from __future__ import annotations

import argparse
import asyncio
import json
import random
from collections import defaultdict

from agent.nodes.agency import route
from evals.harness import RESULTS, ROOT, deps, load_jsonl, reset_gigsim

TEAM = ["ai_ml", "web_dev", "data_analysis"]


async def run(n_jobs: int, variant: str) -> dict:
    reset_gigsim()
    labels = load_jsonl(ROOT / "evals" / "datasets" / "dev" / "labels.jsonl")
    jobs = {j["job_id"]: j for j in load_jsonl(ROOT / "data" / "gigsim_seed" / "jobs.jsonl")}
    gold: dict[str, set[str]] = defaultdict(set)
    flags: dict[str, dict] = {}
    for r in labels:
        flags[r["job_id"]] = r
        if r["bid"]:
            gold[r["job_id"]].add(r["persona"])
    clean = sorted(j for j, r in flags.items() if not r["is_scam"] and not r["has_injection"] and not r["duplicate_of"])
    with_member = [j for j in clean if gold[j]]
    without = [j for j in clean if not gold[j]]
    rng = random.Random(7)
    sample = with_member[: n_jobs * 2 // 3] + rng.sample(without, min(len(without), n_jobs - n_jobs * 2 // 3))
    team = {m: deps(m, variant) for m in TEAM}
    rows = []
    for jid in sample:
        job = jobs[jid]
        r = await route(job, team)
        cat = job["category"] if job["category"] in TEAM else None
        rows.append({"job_id": jid, "gold": sorted(gold[jid]), "chosen": r.chosen, "reason": r.reason,
                     "category_baseline": cat, "random_baseline": rng.choice(TEAM),
                     "fits": {c.member: c.fit for c in r.candidates}})

    def acc(key: str, rs) -> float:
        ok = sum((r[key] in r["gold"]) if r["gold"] else (r[key] is None) for r in rs)
        return round(ok / len(rs), 3) if rs else None

    pos = [r for r in rows if r["gold"]]
    neg = [r for r in rows if not r["gold"]]
    out = {"jobs": len(rows), "variant": variant,
           "routing_accuracy": {k: acc(k, rows) for k in ("chosen", "category_baseline", "random_baseline")},
           "accuracy_when_someone_should_bid": {k: acc(k, pos) for k in ("chosen", "category_baseline", "random_baseline")},
           "no_member_when_nobody_should_bid": {k: acc(k, neg) for k in ("chosen", "category_baseline", "random_baseline")},
           "rows": rows}
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--jobs", type=int, default=150)
    ap.add_argument("--variant", default="v2_hybrid")
    a = ap.parse_args()
    res = asyncio.run(run(a.jobs, a.variant))
    (RESULTS / "agency_routing.json").write_text(json.dumps(res, indent=2), encoding="utf-8")
    for k in ("routing_accuracy", "accuracy_when_someone_should_bid", "no_member_when_nobody_should_bid"):
        print(k, res[k])


if __name__ == "__main__":
    main()
