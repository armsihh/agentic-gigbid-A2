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


def chain_for(node: str, profile: str | None = None) -> list[ModelSpec]:
    """The tier's provider chain, in order: primary, then each `fallback` (e.g. Groq -> Gemini/Gemma -> OpenRouter)."""
    out, s = [], spec_for(node, profile)
    while s is not None and len(out) < 6:
        out.append(s)
        s = s.fallback
    return out


def chat_model(node: str, profile: str | None = None, **overrides: Any):
    """LangChain chat model for a node: the configured provider chain, tried in order on any error.
    Every link but the last gets few retries, so a rate-limited provider hands over quickly."""
    from langchain_openai import ChatOpenAI

    chain = chain_for(node, profile)
    last_retries = int(os.environ.get("LLM_MAX_RETRIES", "3"))

    def make(s: ModelSpec, retries: int):
        prov = _provider(s.provider)
        return ChatOpenAI(model=s.model, base_url=prov["base_url"], api_key=prov["api_key"] or "missing",
                          temperature=overrides.get("temperature", s.temperature),
                          max_tokens=overrides.get("max_tokens", s.max_tokens), timeout=90, max_retries=retries)

    def method(s: ModelSpec) -> str:
        return _cfg()["providers"][s.provider].get("structured_method", "function_calling")

    links = [(make(s, 1 if i < len(chain) - 1 else last_retries), method(s)) for i, s in enumerate(chain)
             if not _cfg()["providers"][s.provider].get("api_key_env") or os.environ.get(
                 _cfg()["providers"][s.provider]["api_key_env"])]          # skip providers with no key configured
    if not links:
        raise RuntimeError(f"no provider with an API key configured for node {node!r}")
    return _ProviderChain(links)


class _ProviderChain:
    """Ordered provider chain. Structured output is applied to EACH link with that provider's method
    (function calling for Groq/OpenRouter, JSON schema for Gemma on the Gemini API), then chained with fallbacks."""
    def __init__(self, links: list[tuple[Any, str]]):
        self.links = links
        self.primary = links[0][0]

    @staticmethod
    def _so(model, schema, method: str, kw: dict):
        k = dict(kw, method=kw.get("method") or method)
        if k["method"] == "json_schema":
            k.setdefault("strict", False)
        return model.with_structured_output(schema, **k)

    def with_structured_output(self, schema, **kw):
        runs = [self._so(m, schema, meth, kw) for m, meth in self.links]
        return runs[0].with_fallbacks(runs[1:]) if len(runs) > 1 else runs[0]

    async def ainvoke(self, *a, **kw):
        models = [m for m, _ in self.links]
        r = models[0].with_fallbacks(models[1:]) if len(models) > 1 else models[0]
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
