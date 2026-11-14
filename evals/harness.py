"""Shared evaluation harness: an in-process GigSim + the real MCP server tools + real (Groq) or fake models.

Every eval runner uses this so results are reproducible: same GigSim seed, same corpus, same config.
"""
from __future__ import annotations

import os
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
# override: a stale key exported in the OS environment silently won over .env (every Gemini call 402-ed)
load_dotenv(ROOT / ".env", override=True)
os.environ.setdefault("GIGSIM_ERROR_RATE", "0")
os.environ.setdefault("GIGSIM_SLOW_RATE", "0")
os.environ.setdefault("GIGSIM_RPM", "100000")

from agent.nodes.common import Deps
from agent.testing import LocalToolbox
from gigsim.app import _buckets
from gigsim.app import app as gigsim_app
from gigsim.app import world as gigsim_world
from mcp_servers.common import local_identity
from mcp_servers.marketplace.adapters.gigsim import GigSimAdapter
from mcp_servers.marketplace.server import build_server as build_marketplace
from mcp_servers.portfolio.server import build_server as build_portfolio
from mcp_servers.portfolio.tools import PortfolioStore
from mcp_servers.workspace.server import WorkspaceStore
from mcp_servers.workspace.server import build_server as build_workspace
from rag.ingest.loaders import load_profile

RESULTS = ROOT / "evals" / "results"
_STORES: dict[str, PortfolioStore] = {}


def load_jsonl(p: Path) -> list[dict]:
    import json
    return [json.loads(x) for x in p.read_text(encoding="utf-8").split("\n") if x.strip()]


def reset_gigsim() -> None:
    gigsim_world.reset()
    _buckets.clear()
    gigsim_world.cfg["faults"].update(error_rate=0, slow_rate=0)
    gigsim_world.cfg["rate_limit"]["requests_per_minute"] = 100000


class PersonaToolbox(LocalToolbox):
    """LocalToolbox that acts as `eval@<persona>` so marketplace/portfolio scoping matches production."""
    def __init__(self, servers, persona: str):
        super().__init__(servers)
        self.identity = f"eval@{persona}"

    async def call(self, agent, tool, args):
        tok = local_identity.set(self.identity)
        try:
            return await super().call(agent, tool, args)
        finally:
            local_identity.reset(tok)


def toolbox(persona: str, variant: str | None = None, workdir: Path | None = None) -> PersonaToolbox:
    workdir = workdir or ROOT / "data" / "runtime" / "eval"
    os.environ.setdefault("AUDIT_LOG_DIR", str(workdir / "audit"))
    key = variant or "config"
    if key not in _STORES:
        _STORES[key] = PortfolioStore(variant=variant)

    def adapter(user: str):
        p = user.rsplit("@", 1)[-1]
        return GigSimAdapter(base_url="http://gigsim", token=f"dev-{p}", transport=httpx.ASGITransport(app=gigsim_app),
                             backoff_base_s=0.01)
    servers = {"marketplace": build_marketplace(adapter, token_spec="", audit_path=str(workdir / "audit" / "m.jsonl")),
               "portfolio": build_portfolio(_STORES[key], token_spec=""),
               "workspace": build_workspace(WorkspaceStore(workdir / "ws"), token_spec="")}
    return PersonaToolbox(servers, persona)


def deps(persona: str, variant: str | None = None, model_factory=None, verifier=None, memory=None) -> Deps:
    from agent.llm import chat_model
    profile = load_profile(ROOT / "data" / "personas" / persona)
    return Deps(toolbox=toolbox(persona, variant), memory=memory, verifier=verifier or default_verifier(),
                profile=profile, model_factory=model_factory or chat_model)


_VER = None


def default_verifier():
    global _VER
    if _VER is None:
        from rag.index.dense import Reranker
        from rag.verify import ClaimVerifier
        skills = set()
        for p in (ROOT / "data" / "personas").iterdir():
            skills |= {s.lower() for s in load_profile(p).get("skills", [])}
        _VER = ClaimVerifier(Reranker(), known_terms=skills | {"kubernetes", "celery", "pinecone", "dbt", "spark"})
    return _VER


__all__ = ["RESULTS", "ROOT", "deps", "gigsim_world", "load_jsonl", "reset_gigsim", "toolbox"]
