"""Shared node plumbing: dependencies, config, structured LLM calls with usage metering, trace steps, budgets."""
from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, TypeVar

import yaml
from pydantic import BaseModel

from agent.llm import UsageMeter, chat_model, spec_for
from agent.prompts import load_prompt

ROOT = Path(__file__).resolve().parents[2]
T = TypeVar("T", bound=BaseModel)


@lru_cache(maxsize=1)
def config() -> dict:
    return yaml.safe_load((ROOT / "agent" / "config.yaml").read_text())


def reload_config() -> dict:
    config.cache_clear()
    return config()


@dataclass
class Deps:
    """Everything nodes need, injected by the graph builder (real MCP toolbox in prod, fakes in tests)."""
    toolbox: Any                                   # agent.mcp_client.Toolbox (or a fake with .call(agent, tool, args))
    memory: Any = None                             # agent.memory.store.MemoryManager
    verifier: Any = None                           # rag.verify.ClaimVerifier
    profile: dict[str, Any] = field(default_factory=dict)   # freelancer profile (rate, floor, skills)
    model_factory: Callable[[str], Any] = chat_model         # node -> chat model (fake in tests)
    meter: UsageMeter = field(default_factory=UsageMeter)


def step(node: str, summary: str, **extra: Any) -> dict:
    return {"node": node, "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "summary": summary[:300], **extra}


def tool_json(result: Any) -> Any:
    """MCP tools via langchain-mcp-adapters return content blocks; structured JSON is in the text block."""
    if isinstance(result, (dict, list)) and not (isinstance(result, list) and result and isinstance(result[0], dict)
                                                 and "type" in result[0]):
        return result
    if isinstance(result, tuple):
        result = result[0]
    if isinstance(result, list):
        text = "".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in result)
    else:
        text = str(getattr(result, "content", result))
    try:
        return json.loads(text)
    except ValueError:
        return {"text": text}


async def structured(deps: Deps, node: str, schema: type[T], system: str, user: str) -> tuple[T, dict]:
    """Call the node's configured model for a Pydantic object. Records tokens/cost/latency for budgets."""
    model = deps.model_factory(node)
    runnable = model.with_structured_output(schema, include_raw=True)
    t0 = time.perf_counter()
    out = await runnable.ainvoke([("system", system), ("user", user)])
    latency = time.perf_counter() - t0
    raw, parsed = out.get("raw"), out.get("parsed")
    if parsed is None:
        raise ValueError(f"{node}: model did not return a valid {schema.__name__}: {out.get('parsing_error')}")
    if isinstance(parsed, dict):
        parsed = schema.model_validate(parsed)
    usage = getattr(raw, "usage_metadata", None) or {}
    try:
        model_name = spec_for(node).model
    except Exception:  # noqa: BLE001 - fake models in tests
        model_name = "fake"
    u = deps.meter.add(node, model_name, int(usage.get("input_tokens", 0)), int(usage.get("output_tokens", 0)), latency)
    return parsed, {"tokens": u["tokens"], "cost_usd": u["cost_usd"], "latency_ms": round(latency * 1000, 1),
                    "model": model_name, "prompt_version": load_prompt(node).version}


def over_budget(state: dict) -> str | None:
    b = config()["budgets"]
    if state.get("steps", 0) >= b["max_graph_steps"]:
        return f"step budget exceeded ({state.get('steps')} >= {b['max_graph_steps']})"
    if state.get("tokens_used", 0) >= b["max_tokens_per_job"]:
        return f"token budget exceeded ({state.get('tokens_used')} >= {b['max_tokens_per_job']})"
    return None
