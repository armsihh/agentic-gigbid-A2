"""Portfolio MCP server (A1): read-only access to a freelancer's evidence.

    uv run python -m mcp_servers.portfolio.server                       # stdio
    PORTFOLIO_MCP_TOKENS="tok:user1:portfolio:read" \
      uv run python -m mcp_servers.portfolio.server --http --port 8102  # Streamable HTTP + bearer auth

Config: PORTFOLIO_DIR (folder of persona folders), PORTFOLIO_PERSONA (default persona for stdio),
PORTFOLIO_USER_PERSONAS ("user:persona,..." tenant scoping for HTTP users), RAG_VARIANT.
"""
from __future__ import annotations

import argparse
import os
import time
from typing import Annotated, Literal

from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import Context, FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field

from mcp_servers.common import (
    AuditLog,
    StaticTokenVerifier,
    current_user,
    default_audit_path,
    trace_id_from,
)
from mcp_servers.portfolio.prompts import register_prompts
from mcp_servers.portfolio.resources import register_resources
from mcp_servers.portfolio.tools import CaseStudy, EvidenceResults, PortfolioStore, SkillList
from rag.retriever import EvidenceFilters

READ = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
EvidenceType = Literal["case_study", "repo_readme", "repo_code", "cv", "review", "past_proposal"]


def build_server(store: PortfolioStore | None = None, token_spec: str | None = None,
                 http_url: str = "http://localhost:8102") -> FastMCP:
    store = store or PortfolioStore()
    token_spec = token_spec if token_spec is not None else os.environ.get("PORTFOLIO_MCP_TOKENS")
    auth_kwargs = {}
    if token_spec or os.environ.get("MCP_SIGNING_KEY"):
        auth_kwargs = {"token_verifier": StaticTokenVerifier(token_spec),
                           "auth": AuthSettings(issuer_url=http_url, resource_server_url=http_url,
                                             required_scopes=["portfolio:read"], validate_token_resource=False)}
    mcp = FastMCP("gigbid-portfolio", instructions=(
        "Read-only access to one freelancer's portfolio: case studies, repositories (README and code), CV, "
        "client reviews and past proposals with outcomes. Use search_evidence to find proof for a job "
        "requirement and cite evidence_id for every claim."), **auth_kwargs)
    audit = AuditLog(default_audit_path("portfolio"))
    user_personas = dict(p.split(":", 1) for p in filter(None, os.environ.get("PORTFOLIO_USER_PERSONAS", "").split(",")))

    def persona() -> str | None:
        user, _ = current_user("PORTFOLIO_USER")
        if user in user_personas:
            return user_personas[user]
        if "@" in user:  # API-minted identity "<user_id>@<persona>"
            return user.rsplit("@", 1)[1]
        return os.environ.get("PORTFOLIO_PERSONA") or None

    def logged(tool: str, args: dict, ctx: Context | None, fn):
        t0 = time.perf_counter()
        user, _ = current_user("PORTFOLIO_USER")
        try:
            res = fn()
            ok = True
            return res
        except ToolError as e:
            res, ok = {"error": str(e)}, False
            raise
        finally:
            audit.write(server="portfolio", user=user, tool=tool, args=args, ok=ok,
                        result={"n_items": len(res.items)} if hasattr(res, "items") and not isinstance(res, dict) else
                        (res if isinstance(res, dict) else {"ok": True}),
                        trace_id=trace_id_from(ctx), duration_ms=(time.perf_counter() - t0) * 1000)

    @mcp.tool(annotations=READ)
    def search_evidence(
        requirement: Annotated[str, Field(min_length=2, max_length=2000,
                                          description="One job requirement or question, e.g. 'Celery background jobs'")],
        k: Annotated[int, Field(ge=1, le=20)] = 5,
        types: Annotated[list[EvidenceType] | None, Field(description="Restrict to evidence types")] = None,
        outcome: Annotated[list[Literal["won", "replied", "ignored"]] | None,
                           Field(description="Past proposals only: keep these outcomes")] = None,
        project: str | None = None,
        since: Annotated[str | None, Field(description="ISO date; only evidence on/after it")] = None,
        ctx: Context | None = None,
    ) -> EvidenceResults:
        """Find portfolio evidence for ONE requirement. Returns items with type, source, date and outcome.
        Call once per requirement rather than with the whole job post."""
        f = EvidenceFilters(persona=persona(), types=types, outcome=outcome, project=project, since=since)
        args = {"requirement": requirement, "k": k} | f.model_dump(exclude_none=True)
        return logged("search_evidence", args, ctx, lambda: store.search(requirement, k, f))

    @mcp.tool(annotations=READ)
    def get_case_study(
        id: Annotated[str, Field(description="Case study id (e.g. ai_ml-cs-ticket-triage) or project slug")],
        ctx: Context | None = None,
    ) -> CaseStudy:
        """Get one full case study with metadata and ids of related items about the same project."""
        def fn():
            cs = store.case_study(id, persona())
            if cs is None:
                raise ToolError(f"[not_found] case study {id!r} not found")
            return cs
        return logged("get_case_study", {"id": id}, ctx, fn)

    @mcp.tool(annotations=READ)
    def list_skills(ctx: Context | None = None) -> SkillList:
        """List the freelancer's skills with how many case studies prove each, and which projects."""
        return logged("list_skills", {}, ctx, lambda: store.skills(persona()))

    register_resources(mcp, store, persona)
    register_prompts(mcp)
    return mcp


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--http", action="store_true")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8102)
    a = ap.parse_args()
    if a.http:
        server = build_server(http_url=f"http://{a.host}:{a.port}")
        server.settings.host, server.settings.port = a.host, a.port
        server.run("streamable-http")
    else:
        build_server().run("stdio")


if __name__ == "__main__":
    main()
