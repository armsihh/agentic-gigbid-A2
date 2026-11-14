"""Model routing by node (config, never code). Every node's model comes from agent/config.yaml `models`.

Profiles:
  open  (required)  open-weight models via any OpenAI-compatible endpoint: Groq / OpenRouter / Together (hosted)
                    or Ollama / vLLM / llama.cpp (local). The deployed link runs on this profile.
  paid  (optional)  any API model, used only where the evaluation shows it beats `open` enough to justify cost.

Cheap, frequent nodes get a small model plus a `fallback`; Writer / Critic / Liaison get the strongest model.
Token usage and USD cost are recorded per node for budgets (R8) via `UsageMeter`.
"""
from __future__ import annotations

import os
import threading
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]


@dataclass
class ModelSpec:
    provider: str
    model: str
    temperature: float = 0.2
    max_tokens: int = 1200
    fallback: ModelSpec | None = None


@lru_cache(maxsize=1)
def _cfg() -> dict:
    return yaml.safe_load((ROOT / "agent" / "config.yaml").read_text())


def profile_name() -> str:
    return os.environ.get("MODEL_PROFILE") or _cfg()["models"].get("profile", "open")


def spec_for(node: str, profile: str | None = None) -> ModelSpec:
    cfg = _cfg()["models"]
    prof = cfg["profiles"][profile or profile_name()]
    entry = prof["nodes"].get(node) or prof["nodes"]["default"]
    tier = prof["tiers"][entry] if isinstance(entry, str) else entry

    def build(t: dict) -> ModelSpec:
        return ModelSpec(provider=t["provider"], model=t["model"], temperature=t.get("temperature", 0.2),
                         max_tokens=t.get("max_tokens", 1200),
                         fallback=build(prof["tiers"][t["fallback"]]) if t.get("fallback") else None)
    return build(tier)


def _provider(name: str) -> dict:
    p = _cfg()["providers"][name]
    return {"base_url": os.environ.get(p.get("base_url_env", ""), "") or p["base_url"],
            "api_key": os.environ.get(p["api_key_env"], "") if p.get("api_key_env") else "not-needed"}


def chat_model(node: str, profile: str | None = None, **overrides: Any):
    """LangChain chat model for a node, with the configured fallback model chained on errors."""
    from langchain_openai import ChatOpenAI

    spec = spec_for(node, profile)

    def make(s: ModelSpec):
        prov = _provider(s.provider)
        return ChatOpenAI(model=s.model, base_url=prov["base_url"], api_key=prov["api_key"],
                          temperature=overrides.get("temperature", s.temperature),
                          max_tokens=overrides.get("max_tokens", s.max_tokens), timeout=90,
                          max_retries=int(os.environ.get("LLM_MAX_RETRIES", "3")))
    return _WithFallback(make(spec), make(spec.fallback) if spec.fallback else None)


class _WithFallback:
    """Primary model + configured fallback. Structured output is applied to EACH model, then chained
    (a RunnableWithFallbacks itself has no with_structured_output)."""
    def __init__(self, primary, fallback):
        self.primary, self.fallback = primary, fallback

    def with_structured_output(self, schema, **kw):
        # function calling is the most portable structured-output method across Groq/OpenRouter/Ollama
        kw.setdefault("method", "function_calling")
        if kw["method"] == "json_schema":
            kw.setdefault("strict", False)
        p = self.primary.with_structured_output(schema, **kw)
        return p.with_fallbacks([self.fallback.with_structured_output(schema, **kw)]) if self.fallback else p

    async def ainvoke(self, *a, **kw):
        r = self.primary.with_fallbacks([self.fallback]) if self.fallback else self.primary
        return await r.ainvoke(*a, **kw)


def price_per_mtok(model: str) -> tuple[float, float]:
    """(input, output) USD per million tokens from config; 0 for local models."""
    p = _cfg().get("pricing_usd_per_mtok", {}).get(model)
    return (p["in"], p["out"]) if p else (0.0, 0.0)


@dataclass
class UsageMeter:
    """Accumulates tokens / cost / latency per node for one thread (R8 budgets, E5)."""
    by_node: dict[str, dict[str, float]] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def add(self, node: str, model: str, tokens_in: int, tokens_out: int, latency_s: float) -> dict[str, float]:
        pin, pout = price_per_mtok(model)
        cost = tokens_in / 1e6 * pin + tokens_out / 1e6 * pout
        with self._lock:
            d = self.by_node.setdefault(node, {"tokens_in": 0, "tokens_out": 0, "cost_usd": 0.0, "latency_s": 0.0, "calls": 0})
            d["tokens_in"] += tokens_in
            d["tokens_out"] += tokens_out
            d["cost_usd"] += cost
            d["latency_s"] += latency_s
            d["calls"] += 1
        return {"tokens": tokens_in + tokens_out, "cost_usd": cost}

    def totals(self) -> dict[str, float]:
        keys = ("tokens_in", "tokens_out", "cost_usd", "latency_s", "calls")
        return {k: sum(d[k] for d in self.by_node.values()) for k in keys}
