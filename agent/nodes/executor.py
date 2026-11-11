"""Executor: the ONLY code that writes to the marketplace, and only after human approval (R4).
Deterministic (no LLM). Idempotency keys are derived from the graph thread id, so replaying a node after a crash
re-sends the same keys and the marketplace returns the original result: submitted exactly once (C6)."""
from __future__ import annotations

import hashlib

from agent.nodes.common import Deps, step, tool_json


def keys(thread_id: str) -> dict[str, str]:
    """Stable per thread; the hash suffix keeps keys valid (8-128 chars, safe charset) for any thread id."""
    safe = "".join(ch if ch.isalnum() or ch in "-_.:" else "-" for ch in thread_id)[:80]
    h = hashlib.sha1(thread_id.encode()).hexdigest()[:10]
    return {"draft": f"draft:{safe}:{h}", "submit": f"submit:{safe}:{h}"}


def _letter(draft: dict) -> dict:
    return {"cover_letter": draft["cover_letter"],
            "screening_answers": [f"{a['question']}\n{a['answer']}" for a in draft.get("screening_answers", [])]}


def make_preview_node(deps: Deps):
    async def preview(state: dict) -> dict:
        d, job, price = state["draft"], state["job"], state["price"]
        res = tool_json(await deps.toolbox.call("executor", "create_proposal_draft", {
            "job_id": job["job_id"], **_letter(d), "bid_amount": price["amount"],
            "idempotency_key": keys(state["thread_id"])["draft"], "dry_run": True}))
        prev = res.get("preview", res) if isinstance(res, dict) else {"raw": res}
        return {"dry_run_preview": prev, "status": "waiting_approval",
                "trace": [step("preview", f"dry run: {prev.get('connects_cost')} connects, balance after "
                                          f"{prev.get('connects_balance_after')}")]}
    return preview


def make_submit_node(deps: Deps):
    async def submit(state: dict) -> dict:
        d, job, price, k = state["draft"], state["job"], state["price"], keys(state["thread_id"])
        created = tool_json(await deps.toolbox.call("executor", "create_proposal_draft", {
            "job_id": job["job_id"], **_letter(d), "bid_amount": price["amount"], "idempotency_key": k["draft"]}))
        pid = (created.get("proposal") or {}).get("proposal_id")
        if not pid:
            raise RuntimeError(f"marketplace did not return a proposal id: {str(created)[:200]}")
        sub = tool_json(await deps.toolbox.call("executor", "submit_proposal",
                                                {"proposal_id": pid, "idempotency_key": k["submit"]}))
        prop = sub.get("proposal") or {}
        return {"submission": {"proposal_id": pid, "status": prop.get("status"), "connects_spent": prop.get("connects_spent")},
                "status": "submitted",
                "trace": [step("submit", f"proposal {pid} {prop.get('status')} (idempotency {k['submit']})")]}
    return submit
