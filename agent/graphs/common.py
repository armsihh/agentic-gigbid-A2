"""Node wrapper shared by both graphs: budgets, timeouts, bounded retries, degraded mode, dead letter."""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from langgraph.errors import GraphBubbleUp

from agent.mcp_client import ServiceDegraded
from agent.nodes.common import over_budget, step

TERMINAL = {"skipped", "watching", "blocked", "rejected", "submitted", "sent"}


def halted(state: dict) -> bool:
    return bool(state.get("halt")) or state.get("status") in TERMINAL


def guarded(name: str, fn: Callable[[dict], Awaitable[dict]], timeout_s: float = 120, attempts: int = 2):
    """Wrap a node: refuse to run over budget; per-node timeout; bounded retries; marketplace outage ->
    queued (recoverable); anything else after retries -> dead letter. Never swallows interrupt()."""
    async def node(state: dict) -> dict:
        reason = over_budget(state)
        if reason:
            return {"halt": "needs_attention", "errors": [f"{name}: {reason}"],
                    "trace": [step(name, f"NEEDS ATTENTION: {reason}")]}
        last = ""
        for attempt in range(1, attempts + 1):
            try:
                out = await asyncio.wait_for(fn(state), timeout=timeout_s)
                return {**out, "steps": 1}
            except GraphBubbleUp:
                raise  # interrupt() / human-in-the-loop: must reach LangGraph
            except ServiceDegraded as e:
                return {"halt": "queued_marketplace_down", "errors": [f"{name}: {e}"],
                        "trace": [step(name, f"QUEUED: {e.server} unavailable, will retry when it recovers")]}
            except Exception as e:  # noqa: BLE001
                last = f"{type(e).__name__}: {e}"
                if attempt < attempts:
                    await asyncio.sleep(0.5 * attempt)
        return {"halt": "dead_letter", "errors": [f"{name}: {last}"],
                "trace": [step(name, f"DEAD LETTER after {attempts} attempts: {last[:200]}")]}
    node.__name__ = name
    return node
