"""Process-wide runtime: MCP toolbox per user, graphs, checkpointer (durable), memory store.

Toolbox modes
  http    MARKETPLACE_MCP_URL / PORTFOLIO_MCP_URL / WORKSPACE_MCP_URL set (docker compose, deployment):
          real MCP over Streamable HTTP with a per-user signed bearer token (user@persona, scoped).
  inproc  no URLs (local dev, tests): the same MCP server objects called in-process (same schemas, validation,
          audit), so the app runs without extra processes. Agents still only see MCP tools.
Persistence: Postgres checkpointer + store when CHECKPOINT_URL/DATABASE_URL is postgres; SQLite files otherwise.
Both survive an API restart, which is what makes approvals durable (C6).
"""
from __future__ import annotations

import os
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any

from agent.graphs.bid_graph import build_bid_graph
from agent.graphs.conversation_graph import build_conversation_graph
from agent.mcp_client import Toolbox, build_connections, load_config
from agent.memory.store import MemoryManager
from agent.nodes.common import Deps
from apps.api.settings import ROOT, get_settings
from mcp_servers.common import sign_token
from rag.ingest.loaders import load_profile

SCOPES = {"marketplace": ["marketplace:read", "marketplace:write"], "portfolio": ["portfolio:read"],
          "workspace": ["workspace:read", "workspace:write"]}


def persona_profile(persona: str, overrides: dict | None = None) -> dict:
    prof = load_profile(ROOT / "data" / "personas" / persona)
    o = overrides or {}
    for k in ("hourly_rate", "min_fixed_budget"):
        if o.get(k):
            prof[k] = float(o[k])
    return prof


class Runtime:
    def __init__(self) -> None:
        self.cfg = load_config()
        self.stack = AsyncExitStack()
        self.checkpointer = None
        self.store = None
        self.memory: MemoryManager | None = None
        self._toolboxes: dict[str, Any] = {}
        self._graphs: dict[tuple[str, str], Any] = {}
        self.mode = "http" if os.environ.get("MARKETPLACE_MCP_URL") else "inproc"
        self._inproc_servers: dict[str, Any] | None = None
        self._verifier = None

    async def start(self) -> None:
        s = get_settings()
        url = s.checkpoint_url or (s.database_url if s.is_postgres else None)
        if url and url.startswith("postgres"):
            from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
            from langgraph.store.postgres import PostgresStore
            url = url.replace("postgresql+psycopg://", "postgresql://")
            self.checkpointer = await self.stack.enter_async_context(AsyncPostgresSaver.from_conn_string(url))
            await self.checkpointer.setup()
            # The memory store is the SYNC PostgresStore: MemoryManager calls it synchronously (small, fast queries),
            # exactly like the SQLite store used locally. AsyncPostgresStore refuses sync calls inside the event loop,
            # which dead-lettered every proposal in production (found on the live site).
            self.store = self.stack.enter_context(PostgresStore.from_conn_string(url))
            self.store.setup()
        else:
            from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
            data = Path(os.environ.get("APP_DATA_DIR", ROOT / "data"))
            data.mkdir(parents=True, exist_ok=True)
            self.checkpointer = await self.stack.enter_async_context(
                AsyncSqliteSaver.from_conn_string(str(data / "checkpoints.db")))
            self.store = self.stack.enter_context(_sqlite_store(data))
        self.memory = MemoryManager(self.store)

    async def stop(self) -> None:
        await self.stack.aclose()

    # ------------------------------------------------------------ tools
    def _inproc(self) -> dict[str, Any]:
        if self._inproc_servers is None:
            from mcp_servers.marketplace.server import build_server as bm
            from mcp_servers.portfolio.server import build_server as bp
            from mcp_servers.workspace.server import build_server as bw
            self._inproc_servers = {"marketplace": bm(token_spec=""), "portfolio": bp(token_spec=""),
                                    "workspace": bw(token_spec="")}
        return self._inproc_servers

    def toolbox(self, user_id: str, persona: str):
        key = f"{user_id}@{persona}"
        if key not in self._toolboxes:
            if self.mode == "http":
                env = {f"{n.upper()}_MCP_TOKEN": sign_token(key, sc) for n, sc in SCOPES.items()}
                self._toolboxes[key] = Toolbox.from_config(self.cfg, build_connections(self.cfg, env=env))
            else:
                self._toolboxes[key] = _ScopedLocalToolbox(self._inproc(), key)
        return self._toolboxes[key]

    def verifier(self):
        if self._verifier is None:
            from rag.index.dense import Reranker
            from rag.verify import ClaimVerifier
            skills = set()
            for p in (ROOT / "data" / "personas").iterdir():
                skills |= {s.lower() for s in load_profile(p).get("skills", [])}
            if os.environ.get("VERIFIER_RELEVANCE") == "embedding":   # 512 MB host: no extra model (rag/index/dense.py)
                from rag.index.dense import Embedder, EmbeddingRelevance
                scorer = EmbeddingRelevance(Embedder(self.cfg["models"]["embeddings"]))
            else:
                scorer = Reranker(self.cfg["models"]["reranker"], batch_size=1, max_chars=600)
            self._verifier = ClaimVerifier(scorer,
                                           known_terms=skills | {"kubernetes", "celery", "pinecone", "dbt", "spark"})
        return self._verifier

    def deps(self, user) -> Deps:
        d = Deps(toolbox=self.toolbox(user.id, user.persona), memory=self.memory, verifier=self.verifier(),
                 profile=persona_profile(user.persona, user.settings))
        if os.environ.get("GIGBID_FAKE_LLM") == "1":  # UI tests / offline demos: scripted models, no API calls
            d.model_factory = _fake_models()
        return d

    def graph(self, user, kind: str):
        key = (user.id, kind)
        if key not in self._graphs:
            build = build_bid_graph if kind == "bid" else build_conversation_graph
            # graph nodes use long-term memory through MemoryManager (deps.memory), not the graph-level store
            self._graphs[key] = build(self.deps(user), checkpointer=self.checkpointer)
        return self._graphs[key]

    def invalidate(self, user_id: str) -> None:
        self._graphs = {k: v for k, v in self._graphs.items() if k[0] != user_id}
        self._toolboxes = {k: v for k, v in self._toolboxes.items() if not k.startswith(user_id + "@")}


def _fake_models():
    """Deterministic model outputs for UI tests (GIGBID_FAKE_LLM=1). Never used in production."""
    from agent.testing import FakeModels
    letter = ("Hi - you need a reliable model added to your existing code. For a UK SaaS helpdesk company I fine-tuned "
              "a classifier on 38k historical tickets that routed 81% of tickets automatically at 94% precision. I would "
              "start by reviewing your current pipeline and data, agree the first feature with you, and ship it behind an "
              "evaluation set so every change is measured before release. I document everything for handover and keep "
              "you updated with short weekly notes. Could you share a sample of the data and the feature you want first?")
    return FakeModels({
        "analyst": [lambda m: {"job_id": "x", "title": "x", "summary": "Add features to an existing model",
                               "requirements": [{"text": "machine learning model work", "skills": ["Machine Learning"]}]}],
        "writer": [{"cover_letter": letter, "screening_answers": [],
                    "claims": [{"text": "fine-tuned a classifier on 38k historical tickets",
                                "evidence_ids": ["ai_ml-cs-ticket-triage#2"]}]}],
        "critic": [{"approve": True, "grounding": 5, "personalisation": 4, "length_ok": True}],
        "intent": [{"intent": "question", "reason": "asks about experience"}],
        "client_liaison": [{"text": "Thanks for asking! I built a support ticket classifier for a UK SaaS company. "
                                    "Happy to share more details here.", "proposed_slot_starts": []}],
    })


def _sqlite_store(data: Path):
    """SqliteStore with a thread-safe connection (the API serves requests from a thread pool too)."""
    import sqlite3

    from langgraph.store.sqlite import SqliteStore
    conn = sqlite3.connect(str(data / "memory.db"), check_same_thread=False, isolation_level=None)
    st = SqliteStore(conn)
    st.setup()
    return _Closing(st, conn)


class _Closing:
    def __init__(self, store, conn):
        self.store, self.conn = store, conn

    def __enter__(self):
        return self.store

    def __exit__(self, *a):
        self.conn.close()


class _ScopedLocalToolbox:
    """In-process toolbox acting as `user@persona` (same identity the HTTP mode would carry)."""
    def __init__(self, servers, identity: str):
        from agent.testing import LocalToolbox
        self.inner = LocalToolbox(servers)
        self.identity = identity

    async def call(self, agent: str, tool: str, args: dict):
        from mcp_servers.common import local_identity
        tok = local_identity.set(self.identity)
        try:
            return await self.inner.call(agent, tool, args)
        finally:
            local_identity.reset(tok)


runtime = Runtime()
