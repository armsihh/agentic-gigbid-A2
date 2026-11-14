"""Judge calibration (B4): agreement between the LLM judge and the author's own labels on 30 proposals.

Inputs: evals/datasets/judge_calibration_items.jsonl (30 proposals) and evals/datasets/judge_labels.csv (my 1-5
scores, filled in by hand before looking at the judge). Output: Cohen's kappa (exact and quadratic-weighted),
exact / within-1 agreement, and the biggest disagreements -> evals/results/judge_calibration.json.
Judge scores are cached (evals/results/judge_cache.json) so a rate-limited run resumes where it stopped.

    uv run python -m evals.runners.judge_calibration
"""
from __future__ import annotations

import asyncio
import csv
import json
import re

from evals.harness import RESULTS, ROOT, load_jsonl
from evals.runners.proposal_eval import JudgeScore

NL = "\n"
RETRY = re.compile(r"try again in (?:(\d+)m)?([\d.]+)s")


def kappa(a: list[int], b: list[int], weighted: bool = False, k: int = 5) -> float:
    n = len(a)
    obs = [[0] * k for _ in range(k)]
    for x, y in zip(a, b):
        obs[x - 1][y - 1] += 1
    ra = [sum(r) for r in obs]
    cb = [sum(obs[i][j] for i in range(k)) for j in range(k)]

    def w(i: int, j: int) -> float:
        return ((i - j) ** 2) / ((k - 1) ** 2) if weighted else float(i != j)
    po = sum(w(i, j) * obs[i][j] for i in range(k) for j in range(k)) / n
    pe = sum(w(i, j) * ra[i] * cb[j] for i in range(k) for j in range(k)) / (n * n)
    return round(1 - po / pe, 3) if pe else 1.0


async def judge_all(items: list[dict]) -> dict[str, dict]:
    from agent.guardrails.injection import wrap_untrusted
    from agent.nodes.common import Deps, structured
    from agent.prompts import load_prompt
    cache_p = RESULTS / "judge_cache.json"
    out = json.loads(cache_p.read_text()) if cache_p.exists() else {}
    for it in items:
        if it["item_id"] in out:
            continue
        user = (wrap_untrusted("job_post", it["job_title"] + NL + it["job_description"]) + NL + NL
                + "PROPOSAL:" + NL + it["proposal"])
        for attempt in range(30):
            try:
                s, _ = await structured(Deps(toolbox=None), "judge", JudgeScore, load_prompt("judge").render(), user)
                out[it["item_id"]] = s.model_dump()
                cache_p.write_text(json.dumps(out, indent=1))
                break
            except Exception as e:
                if attempt == 29:
                    raise
                m = RETRY.search(str(e))
                wait = min(900.0, int(m.group(1) or 0) * 60 + float(m.group(2)) + 5) if m else 30.0 * (attempt + 1)
                print(f"  rate limited, waiting {wait:.0f}s", flush=True)
                await asyncio.sleep(wait)
    return out


def main() -> None:
    items = load_jsonl(ROOT / "evals" / "datasets" / "judge_calibration_items.jsonl")
    with (ROOT / "evals" / "datasets" / "judge_labels.csv").open(encoding="utf-8") as f:
        mine = {r["item_id"]: int(r["your_score"]) for r in csv.DictReader(f) if r["your_score"].strip()}
    items = [i for i in items if i["item_id"] in mine]
    if len(items) < 30:
        print(f"warning: only {len(items)} labelled items (need 30)")
    judged = asyncio.run(judge_all(items))
    a = [mine[i["item_id"]] for i in items]
    b = [judged[i["item_id"]]["overall"] for i in items]
    rows = [{"item_id": i["item_id"], "source": i["source"], "mine": x, "judge": y,
             "judge_justification": judged[i["item_id"]]["justification"]} for i, x, y in zip(items, a, b)]
    res = {"n": len(items), "cohen_kappa": kappa(a, b), "cohen_kappa_quadratic": kappa(a, b, weighted=True),
           "exact_agreement": round(sum(x == y for x, y in zip(a, b)) / len(a), 3),
           "within_one": round(sum(abs(x - y) <= 1 for x, y in zip(a, b)) / len(a), 3),
           "mean_mine": round(sum(a) / len(a), 2), "mean_judge": round(sum(b) / len(b), 2),
           "biggest_disagreements": sorted(rows, key=lambda r: -abs(r["mine"] - r["judge"]))[:5], "rows": rows}
    (RESULTS / "judge_calibration.json").write_text(json.dumps(res, indent=2), encoding="utf-8")
    print({k: v for k, v in res.items() if k not in ("rows", "biggest_disagreements")})


if __name__ == "__main__":
    main()
