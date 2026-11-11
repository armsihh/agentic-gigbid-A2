"""Retrieval evaluation (B4): evidence Recall@5, MRR, nDCG@10 against gold evidence projects, per persona
and job type, plus latency; refusal quality for corrective variants. Writes evals/results/rag_retrieval_<split>.json.

    uv run python -m evals.runners.rag_eval                       # all variants on dev
    uv run python -m evals.runners.rag_eval --limit 40            # smoke (40 jobs per persona)
    uv run python -m evals.runners.rag_eval --ablation v5_multivector
"""
from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path

import numpy as np

from rag.ingest.loaders import load_corpus
from rag.retriever import EvidenceFilters
from rag.variants import VARIANTS, build_variant

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "evals" / "results"
PERSONAS = ["ai_ml", "web_dev", "data_analysis"]


def load_jsonl(p: Path) -> list[dict]:
    return [json.loads(x) for x in p.read_text(encoding="utf-8").split("\n") if x.strip()]


def project_ranking(results) -> list[str]:
    seen, out = set(), []
    for r in results:
        p = r.chunk.project
        if p and p not in seen:
            seen.add(p)
            out.append(p)
    return out


def metrics(ranked: list[str], gold: set[str]) -> dict[str, float]:
    rec5 = len(set(ranked[:5]) & gold) / len(gold)
    mrr = next((1.0 / (i + 1) for i, p in enumerate(ranked) if p in gold), 0.0)
    dcg = sum(1.0 / math.log2(i + 2) for i, p in enumerate(ranked[:10]) if p in gold)
    idcg = sum(1.0 / math.log2(i + 2) for i in range(min(len(gold), 10)))
    return {"recall@5": rec5, "mrr": mrr, "ndcg@10": dcg / idcg}


def evaluate(variant: str, labels: list[dict], jobs: dict, chunks, limit: int | None, **overrides) -> dict:
    pipe = build_variant(variant, chunks, **overrides)
    per_rows, lat, refusals = [], [], []
    for persona in PERSONAS:
        rows = [r for r in labels if r["persona"] == persona and not r["is_scam"] and not r["duplicate_of"]]
        pos = [r for r in rows if r["gold_evidence_projects"]]
        neg = [r for r in rows if not r["gold_evidence_projects"] and r["category"] != persona]  # clearly off-profile
        if limit:
            pos, neg = pos[:limit], neg[: max(5, limit // 4)]
        f = EvidenceFilters(persona=persona, types=["case_study", "repo_readme", "repo_code", "cv", "review",
                                                    "past_proposal"])
        for r in pos:
            t0 = time.perf_counter()
            res = pipe.search_job(jobs[r["job_id"]], k=30, filters=f)
            lat.append(time.perf_counter() - t0)
            m = metrics(project_ranking(res), set(r["gold_evidence_projects"]))
            per_rows.append({"persona": persona, "job_type": "4+ reqs" if r["n_requirements"] >= 4 else "<4 reqs",
                             "refused": pipe.last_trace.refused, **m})
        if pipe.cfg.corrective:
            for r in neg:
                pipe.search_job(jobs[r["job_id"]], k=30, filters=f)
                refusals.append(pipe.last_trace.refused)

    def agg(rows):
        if not rows:
            return {}
        return {k: round(float(np.mean([x[k] for x in rows])), 4) for k in ("recall@5", "mrr", "ndcg@10")} | {"n": len(rows)}

    out = {"variant": variant, "overrides": overrides, "overall": agg(per_rows),
           "by_persona": {p: agg([x for x in per_rows if x["persona"] == p]) for p in PERSONAS},
           "by_job_type": {t: agg([x for x in per_rows if x["job_type"] == t]) for t in ("4+ reqs", "<4 reqs")},
           "latency_s": {"p50": round(float(np.percentile(lat, 50)), 3), "p95": round(float(np.percentile(lat, 95)), 3)}}
    if pipe.cfg.corrective:
        out["corrective"] = {"refusal_rate_on_off_profile_jobs": round(float(np.mean(refusals)), 3) if refusals else None,
                             "false_refusal_rate_on_jobs_with_evidence": round(float(np.mean([x["refused"] for x in per_rows])), 3)}
    return out


ABLATIONS = {  # one stage flipped at a time, relative to the variant under study
    "-rerank": {"rerank": None},
    "-hybrid(dense only)": {"retrieval": "dense"},
    "-decompose(whole post)": {"query": "whole"},
    "-grouping": {"group": False},
    "+outcome": {"outcome": 1.0},
    "fixed chunks": {"chunking": "fixed"},
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="dev")
    ap.add_argument("--variants", nargs="*", default=VARIANTS)
    ap.add_argument("--limit", type=int, default=None, help="jobs per persona (smoke runs)")
    ap.add_argument("--ablation", default=None, help="variant to ablate one stage at a time")
    ap.add_argument("--tag", default="")
    a = ap.parse_args()

    labels = load_jsonl(ROOT / "evals" / "datasets" / a.split / "labels.jsonl")
    jobs = {j["job_id"]: j for j in load_jsonl(ROOT / "data" / "gigsim_seed" / "jobs.jsonl")}
    chunks = load_corpus(ROOT / "data" / "personas")
    runs = []
    if a.ablation:
        runs.append(("full", evaluate(a.ablation, labels, jobs, chunks, a.limit)))
        for label, ov in ABLATIONS.items():
            runs.append((label, evaluate(a.ablation, labels, jobs, chunks, a.limit, **ov)))
    else:
        for v in a.variants:
            t0 = time.time()
            runs.append((v, evaluate(v, labels, jobs, chunks, a.limit)))
            print(f"  {v}: {runs[-1][1]['overall']}  ({time.time() - t0:.0f}s)", flush=True)

    RESULTS.mkdir(parents=True, exist_ok=True)
    name = f"rag_{'ablation_' + a.ablation if a.ablation else 'retrieval'}_{a.split}{'_' + a.tag if a.tag else ''}"
    meta = {"split": a.split, "limit_per_persona": a.limit, "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "embedder": runs[0][1] and build_variant.__module__}
    (RESULTS / f"{name}.json").write_text(json.dumps({"meta": meta, "runs": dict(runs)}, indent=2), encoding="utf-8")

    print("\n| run | Recall@5 | MRR | nDCG@10 | n | p95 latency (s) |\n|---|---|---|---|---|---|")
    for label, r in runs:
        o = r["overall"]
        print(f"| {label} | {o['recall@5']:.3f} | {o['mrr']:.3f} | {o['ndcg@10']:.3f} | {o['n']} | {r['latency_s']['p95']} |")
    print(f"\nwrote {RESULTS / (name + '.json')}")


if __name__ == "__main__":
    main()
