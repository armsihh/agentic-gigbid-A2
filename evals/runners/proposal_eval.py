"""Proposal quality + outcome evaluation (B3, B4, R&D B): runs the REAL bid graph (Groq models) on a fixed job set
for each retrieval variant, then submits to GigSim and fast-forwards the simulated clients.

Per variant: unsupported claims per proposal before / after claim verification, LLM-judge rubric score, critic
revisions, compliance blocks, GigSim reply + hire rate, p50/p95 latency, tokens and USD per proposal.
Also writes evals/results/judge_items.jsonl: the proposals for human labelling (judge calibration).

    LLM_MAX_RETRIES=8 uv run python -m evals.runners.proposal_eval --per-persona 4 --variants v0_naive v5_multivector
"""
from __future__ import annotations

import argparse
import asyncio
import json
import time

import numpy as np
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from pydantic import BaseModel, Field

from agent.state import halt_of
from evals.harness import RESULTS, ROOT, deps, gigsim_world, load_jsonl, reset_gigsim

PERSONAS = ["ai_ml", "web_dev", "data_analysis"]


class JudgeScore(BaseModel):
    relevance: int = Field(ge=1, le=5)
    specificity: int = Field(ge=1, le=5)
    grounding: int = Field(ge=1, le=5)
    clarity: int = Field(ge=1, le=5)
    overall: int = Field(ge=1, le=5)
    justification: str


async def wait_for_quota(min_tokens: int = 30000) -> None:
    """Free tier: don't start a job (~15-30k tokens) unless the writer model has daily quota left; otherwise it would
    dead-letter half-way. Probes with a 1-token request and waits in 10-minute steps."""
    import os

    import httpx

    from agent.llm import spec_for
    if spec_for("writer").provider != "groq":   # only Groq's free tier has the tight daily cap this guards against
        return
    model, key = spec_for("writer").model, os.environ.get("GROQ_API_KEY", "")
    while True:
        try:
            async with httpx.AsyncClient(timeout=30) as c:
                r = await c.post("https://api.groq.com/openai/v1/chat/completions",
                                 headers={"Authorization": f"Bearer {key}"},
                                 json={"model": model, "messages": [{"role": "user", "content": "hi"}], "max_tokens": 1})
            if r.status_code == 200:
                return
        except httpx.HTTPError:
            pass
        print(f"  waiting for {model} quota...", flush=True)
        await asyncio.sleep(600)


def pick_jobs(per_persona: int, split: str = "dev") -> list[tuple[str, str]]:
    labels = load_jsonl(ROOT / "evals" / "datasets" / split / "labels.jsonl")
    jobs = {j["job_id"]: j for j in load_jsonl(ROOT / "data" / "gigsim_seed" / "jobs.jsonl")}
    out = []
    for p in PERSONAS:
        cands = sorted(r["job_id"] for r in labels if r["persona"] == p and r["bid"] and jobs[r["job_id"]]["release_order"] == 0
                       and len(jobs[r["job_id"]]["description"]) > 300)
        step = max(1, len(cands) // per_persona)
        out += [(p, j) for j in cands[::step][:per_persona]]
    return out


async def judge(d, job: dict, draft: dict, evidence: list[dict]) -> dict:
    from agent.guardrails.injection import wrap_untrusted
    from agent.nodes.common import structured
    from agent.nodes.writer import render_evidence
    from agent.prompts import load_prompt
    user = (f"{wrap_untrusted('job_post', job['description'][:2500])}\n\nPROPOSAL:\n{draft['cover_letter']}\n\n"
            f"EVIDENCE the freelancer has:\n{render_evidence(evidence, 10)}")
    s, _ = await structured(d, "judge", JudgeScore, load_prompt("judge").render(), user)
    return s.model_dump()


async def run_variant(variant: str, picks: list[tuple[str, str]]) -> tuple[dict, list[dict], list[dict]]:
    from agent.graphs.bid_graph import build_bid_graph, initial_state
    reset_gigsim()
    for p in PERSONAS:
        gigsim_world.account(p).connects = 10_000
    gigsim_world.policy["proposals"]["max_open_proposals"] = 1000
    rows, items = [], []
    for persona, job_id in picks:
        await wait_for_quota()
        d = deps(persona, variant)
        g = build_bid_graph(d, InMemorySaver())
        tid = f"eval-{variant}-{job_id}"
        cfg = {"configurable": {"thread_id": tid}}
        job = dict(gigsim_world.jobs[job_id])
        t0 = time.perf_counter()
        out = None
        for attempt in range(6):   # free tier: a daily-cap 429 mid-run dead-letters the thread; wait and redo it
            tid_a = f"{tid}-{attempt}"
            cfg = {"configurable": {"thread_id": tid_a}}
            try:
                out = await g.ainvoke(initial_state(job, tid_a, "eval", persona), cfg)
            except Exception as e:  # noqa: BLE001
                out = {"halt": "dead_letter", "errors": [f"{type(e).__name__}: {e}"]}
            if out.get("halt") == "dead_letter" and any("429" in x for x in out.get("errors", [])):
                print(f"  {job_id}: rate limited (daily cap), waiting 15 min then retrying", flush=True)
                await asyncio.sleep(900)
                await wait_for_quota()
                d = deps(persona, variant)
                g = build_bid_graph(d, InMemorySaver())
                t0 = time.perf_counter()
                continue
            break
        if out is None or (out.get("halt") == "dead_letter" and not out.get("draft")):
            rows.append({"job_id": job_id, "persona": persona, "error": "; ".join((out or {}).get("errors", []))[:300]})
            continue
        latency = time.perf_counter() - t0
        row = {"job_id": job_id, "persona": persona, "latency_s": round(latency, 1), "halt": halt_of(out),
               "status": out.get("status"), "action": (out.get("decision") or {}).get("action"),
               "tokens": d.meter.totals()["tokens_in"] + d.meter.totals()["tokens_out"],
               "cost_usd": round(d.meter.totals()["cost_usd"], 6), "errors": out.get("errors", [])}
        if "__interrupt__" in out and out.get("draft"):
            ver = out.get("verification") or {}
            row |= {"claims_checked": ver.get("claims_checked", 0), "unsupported_before": ver.get("unsupported_before", 0),
                    "revisions": out.get("revisions", 0), "compliance_violations": len((out.get("compliance") or {}).get("violations", [])),
                    "words": len(out["draft"]["cover_letter"].split())}
            # unsupported AFTER verification: re-check the cleaned draft with the same verifier
            from rag.verify import Evidence
            ev = [Evidence(evidence_id=e["evidence_id"], text=f"{e.get('title', '')}\n{e.get('text', '')}") for e in out.get("evidence") or []]
            row["unsupported_after"] = len(d.verifier.verify(out["draft"]["cover_letter"], ev).removed)
            try:
                row["judge"] = await judge(d, job, out["draft"], out.get("evidence") or [])
            except Exception as e:  # noqa: BLE001
                row["judge_error"] = str(e)[:200]
            items.append({"item_id": f"{variant}:{job_id}", "variant": variant, "persona": persona, "job_title": job["title"],
                          "job_description": job["description"][:1500], "proposal": out["draft"]["cover_letter"],
                          "judge_overall": (row.get("judge") or {}).get("overall")})
            out2 = await g.ainvoke(Command(resume={"action": "approve", "approver": "eval"}), cfg)
            row["submitted"] = out2.get("status") == "submitted"
        rows.append(row)
        print(f"  [{variant}] {persona} {job_id}: {row.get('status')} {row.get('halt') or ''} "
              f"unsupported {row.get('unsupported_before')}->{row.get('unsupported_after')} judge {(row.get('judge') or {}).get('overall')} "
              f"{row['latency_s']}s", flush=True)
    gigsim_world.fast_forward()
    gigsim_world.fast_forward()
    for r in rows:
        if r.get("submitted"):
            acc = gigsim_world.account(r["persona"])
            st = next((p["status"] for p in acc.proposals.values() if p["job_id"] == r["job_id"] and p["status"] != "draft"), None)
            r["outcome"] = st
    return summarise(variant, rows), rows, items


def summarise(variant: str, rows: list[dict]) -> dict:
    props = [r for r in rows if r.get("claims_checked") is not None]
    sub = [r for r in rows if r.get("submitted")]
    lat = [r["latency_s"] for r in rows if "latency_s" in r]
    js = [r["judge"]["overall"] for r in props if r.get("judge")]
    return {"variant": variant, "jobs": len(rows), "proposals": len(props),
            "unsupported_per_proposal_before": round(float(np.mean([r["unsupported_before"] for r in props])), 3) if props else None,
            "unsupported_per_proposal_after": round(float(np.mean([r["unsupported_after"] for r in props])), 3) if props else None,
            "claims_per_proposal": round(float(np.mean([r["claims_checked"] for r in props])), 2) if props else None,
            "judge_overall_mean": round(float(np.mean(js)), 2) if js else None,
            "critic_revisions_mean": round(float(np.mean([r["revisions"] for r in props])), 2) if props else None,
            "reply_rate": round(sum(r.get("outcome") in ("replied", "interview", "hired") for r in sub) / len(sub), 3) if sub else None,
            "hire_rate": round(sum(r.get("outcome") == "hired" for r in sub) / len(sub), 3) if sub else None,
            "p50_latency_s": float(np.percentile(lat, 50)) if lat else None,
            "p95_latency_s": float(np.percentile(lat, 95)) if lat else None,
            "tokens_per_proposal": round(float(np.mean([r["tokens"] for r in props]))) if props else None,
            "usd_per_proposal": round(float(np.mean([r["cost_usd"] for r in props])), 5) if props else None,
            "errors": sum(1 for r in rows if r.get("error") or r.get("halt"))}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-persona", type=int, default=4)
    ap.add_argument("--variants", nargs="*", default=["v0_naive", "v5_multivector"])
    a = ap.parse_args()
    picks = pick_jobs(a.per_persona)
    print(f"{len(picks)} jobs x {len(a.variants)} variants")
    import os as _os
    prof = _os.environ.get("MODEL_PROFILE", "open")
    prev = RESULTS / f"proposal_eval_{prof}.json"
    summaries, all_rows, items = {}, {}, []
    if prev.exists():   # keep variants finished by an earlier run (re-running one variant must not drop the others)
        old = json.loads(prev.read_text(encoding="utf-8"))
        summaries = {k: v for k, v in old["summaries"].items() if k not in a.variants}
        all_rows = {k: v for k, v in old["rows"].items() if k not in a.variants}
        items_path = RESULTS / f"judge_items_{prof}.jsonl"
        if items_path.exists():
            items = [i for i in load_jsonl(items_path) if i["variant"] not in a.variants]
    for v in a.variants:
        s, rows, its = asyncio.run(run_variant(v, picks))
        summaries[v], all_rows[v] = s, rows
        items += its
        print(json.dumps(s, indent=1), flush=True)
        if any(x.get("proposals") for x in summaries.values()):   # never overwrite results with an empty run
            (RESULTS / f"proposal_eval_{prof}.json").write_text(json.dumps({"summaries": summaries, "rows": all_rows,
                                                               "jobs": picks}, indent=2), encoding="utf-8")
            (RESULTS / f"judge_items_{prof}.jsonl").write_text("".join(json.dumps(i) + "\n" for i in items), encoding="utf-8")
    print(f"wrote {RESULTS / 'proposal_eval.json'}")


if __name__ == "__main__":
    main()
