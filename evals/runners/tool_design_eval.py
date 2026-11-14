"""R&D question A: does tool granularity change agent behaviour?

Same tasks, three tool sets, one model choosing ONE tool call per task (nothing executed):
  fine    many narrow tools (one per field / per evidence type)
  coarse  two generic tools: marketplace(action, params) and portfolio(action, params)
  ours    the real MCP tool schemas + descriptions shipped by our servers (tests/contract/snapshots)
Metrics: tool-selection accuracy, argument accuracy (expected key/values present), tokens per task.

    uv run python -m evals.runners.tool_design_eval [--limit N] [--node analyst]
"""
from __future__ import annotations

import argparse
import asyncio
import json

from evals.harness import RESULTS, ROOT

SNAP = ROOT / "tests" / "contract" / "snapshots"
SYSTEM = ("You are an agent for a freelancer. Call exactly ONE tool that best answers the user's request, with the "
          "right arguments. Do not answer in text.")


def ours() -> list[dict]:
    tools = []
    for server in ("marketplace", "portfolio"):
        snap = json.loads((SNAP / f"{server}.json").read_text(encoding="utf-8"))
        for name, t in snap["tools"].items():
            if name in ("create_proposal_draft", "send_message"):
                continue
            tools.append({"type": "function", "function": {"name": name, "description": t["description"],
                                                           "parameters": t["inputSchema"]}})
    return tools


def _fn(name: str, desc: str, props: dict, req: list[str] | None = None) -> dict:
    return {"type": "function", "function": {"name": name, "description": desc,
                                             "parameters": {"type": "object", "properties": props, "required": req or []}}}


S = {"type": "string"}


def fine() -> list[dict]:
    jid, cid = {"job_id": S}, {"client_id": S}
    cat = {"category": {"type": "string", "enum": ["ai_ml", "web_dev", "data_analysis", "other"]}}
    return [
        _fn("search_jobs_by_category", "Search jobs in a category", cat, ["category"]),
        _fn("search_jobs_by_keyword", "Search jobs by keyword", {"keyword": S}, ["keyword"]),
        _fn("search_hourly_jobs", "Search hourly jobs", cat),
        _fn("search_new_jobs", "Search jobs posted after a time", {"posted_after": S}, ["posted_after"]),
        _fn("get_job_description", "Get a job's description", jid, ["job_id"]),
        _fn("get_job_budget", "Get a job's budget", jid, ["job_id"]),
        _fn("get_job_connects_cost", "Get Connects needed for a job", jid, ["job_id"]),
        _fn("get_job_skills", "Get a job's skills", jid, ["job_id"]),
        _fn("get_client_payment_status", "Client payment verification and spend", cid, ["client_id"]),
        _fn("get_client_hire_rate", "Client hire rate", cid, ["client_id"]),
        _fn("get_client_reviews", "Client rating and reviews", cid, ["client_id"]),
        _fn("get_connects_balance", "Connects balance", {}),
        _fn("get_fixed_price_stats", "Fixed price stats for a category", cat, ["category"]),
        _fn("get_hourly_rate_stats", "Hourly rate stats for a category", cat, ["category"]),
        _fn("get_policy_rules", "Marketplace policy", {}),
        _fn("list_threads", "List conversations", {}),
        _fn("get_thread_messages", "Messages of a thread", {"thread_id": S}, ["thread_id"]),
        _fn("list_replied_proposals", "Proposals that got replies", {}),
        _fn("list_all_proposals", "All proposals", {}),
        _fn("list_events", "Events after a sequence number", {"after": {"type": "integer"}}),
        _fn("preview_submission_cost", "Preview the cost of submitting a proposal", {"proposal_id": S}, ["proposal_id"]),
        _fn("search_case_studies", "Search case studies", {"query": S}, ["query"]),
        _fn("search_repo_code", "Search repository code", {"query": S}, ["query"]),
        _fn("search_past_proposals", "Search past proposals", {"query": S, "outcome": S}, ["query"]),
        _fn("search_reviews", "Search client reviews", {"query": S}, ["query"]),
        _fn("get_case_study", "Get a case study", {"id": S}, ["id"]),
        _fn("list_skills", "List skills", {}),
    ]


def coarse() -> list[dict]:
    p = {"action": S, "params": {"type": "object"}}
    return [_fn("marketplace", "Do anything on the freelance marketplace: action + params", p, ["action"]),
            _fn("portfolio", "Look up anything in the freelancer's portfolio: action + params", p, ["action"])]


def _wait_s(err: str, attempt: int) -> float:
    """Honour Groq's 'Please try again in 5m32.2s' on 429s (rolling daily window), capped at 10 minutes."""
    import re
    m = re.search(r"try again in (?:(\d+)m)?([\d.]+)s", err)
    if "429" in err and m:
        return min(600.0, int(m.group(1) or 0) * 60 + float(m.group(2)) + 2)
    return 20.0 * (attempt + 1) if "429" in err else 2.0


def args_ok(expected: dict, got: dict, coarse_set: bool) -> bool:
    if coarse_set:
        got = {**(got.get("params") or {}), "action": got.get("action")}
    for k, v in expected.items():
        g = got.get(k)
        if g is None:
            return False
        if isinstance(v, str) and v.lower() not in str(g).lower():
            return False
        if isinstance(v, (bool, int)) and g != v:
            return False
        if isinstance(v, list) and not set(map(str, v)) <= set(map(str, g if isinstance(g, list) else [g])):
            return False
    return True


async def run(limit: int | None, node: str, sets: list[str]) -> dict:
    from agent.llm import chat_model, spec_for
    tasks = json.loads((ROOT / "evals" / "datasets" / "tool_tasks.json").read_text(encoding="utf-8"))[:limit]
    model = chat_model(node).primary
    path = RESULTS / "tool_design.json"
    out = json.loads(path.read_text()) if path.exists() else {"model": spec_for(node).model, "n_tasks": len(tasks), "sets": {}}
    for name, tools in (("fine", fine()), ("coarse", coarse()), ("ours", ours())):
        if name not in sets:
            continue
        bound = model.bind_tools(tools, tool_choice="required")
        sel = arg = toks = 0
        rows = []
        for t in tasks:
            exp_tool, exp_args = t[name]
            msg, malformed = None, False
            for attempt in range(60):   # free tier: a daily (TPD) cap frees on a rolling window; wait it out
                try:
                    msg = await bound.ainvoke([("system", SYSTEM), ("user", t["q"])])
                    break
                except Exception as e:
                    if "parse tool call" in str(e) or "tool_use_failed" in str(e):
                        malformed = True  # the model emitted an invalid tool call: counted as a miss
                        break
                    if attempt == 59:
                        raise
                    w = _wait_s(str(e), attempt)
                    print(f"  {name}: rate limited, waiting {w:.0f}s", flush=True)
                    await asyncio.sleep(w)
            if msg is None:
                from langchain_core.messages import AIMessage
                msg = AIMessage(content="")
            call = (msg.tool_calls or [{}])[0]
            ok_tool = call.get("name") == exp_tool
            if name == "coarse":
                ok_tool = ok_tool and exp_args["action"] in str(call.get("args", {}).get("action", ""))
            ok_args = ok_tool and args_ok(exp_args, call.get("args") or {}, name == "coarse")
            u = msg.usage_metadata or {}
            sel, arg, toks = sel + ok_tool, arg + ok_args, toks + u.get("total_tokens", 0)
            rows.append({"q": t["q"], "expected": exp_tool, "got": call.get("name"), "args": call.get("args"),
                         "tool_ok": ok_tool, "args_ok": ok_args, "malformed": malformed, "tokens": u.get("total_tokens", 0)})
            await asyncio.sleep(1.2)  # stay under the free tier's tokens-per-minute cap
        out["sets"][name] = {"tools": len(tools), "tool_selection_accuracy": round(sel / len(tasks), 3),
                             "argument_accuracy": round(arg / len(tasks), 3),
                             "tokens_per_task": round(toks / len(tasks)), "rows": rows}
        path.write_text(json.dumps(out, indent=2), encoding="utf-8")  # save after every set
        print(f"{name:7s} tools={len(tools):2d} selection={sel / len(tasks):.2f} args={arg / len(tasks):.2f} "
              f"tokens/task={toks / len(tasks):.0f}", flush=True)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--node", default="analyst", help="config node whose model is used (small tier)")
    ap.add_argument("--sets", nargs="*", default=["fine", "coarse", "ours"])
    a = ap.parse_args()
    asyncio.run(run(a.limit, a.node, a.sets))
    print(f"wrote {RESULTS / 'tool_design.json'}")


if __name__ == "__main__":
    main()
