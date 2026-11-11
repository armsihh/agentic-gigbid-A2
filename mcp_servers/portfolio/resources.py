"""Resource templates so an MCP host can load full portfolio items into context."""
from __future__ import annotations

import json
from collections.abc import Callable

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ResourceError

from mcp_servers.portfolio.tools import PortfolioStore


def register_resources(mcp: FastMCP, store: PortfolioStore, persona: Callable[[], str | None]) -> None:
    @mcp.resource("portfolio://profile", mime_type="application/json")
    def profile() -> str:
        """The freelancer's profile: headline, rates, skills."""
        return json.dumps(store.profile(persona()), indent=2)

    @mcp.resource("portfolio://case/{case_id}", mime_type="text/markdown")
    def case(case_id: str) -> str:
        """A full case study by id (e.g. ai_ml-cs-ticket-triage) or project slug."""
        cs = store.case_study(case_id, persona())
        if cs is None:
            raise ResourceError(f"case study {case_id} not found")
        return cs.markdown

    @mcp.resource("portfolio://proposal/{proposal_id}", mime_type="application/json")
    def proposal(proposal_id: str) -> str:
        """A past proposal with its outcome (won / replied / ignored)."""
        chunks = [c for c in store.item(proposal_id, persona()) if c.type == "past_proposal"]
        if not chunks:
            raise ResourceError(f"proposal {proposal_id} not found")
        return chunks[0].model_dump_json(indent=2)

    @mcp.resource("portfolio://repo/{repo_id}", mime_type="text/markdown")
    def repo(repo_id: str) -> str:
        """A repository: README plus code files, concatenated."""
        chunks = [c for c in store.item(repo_id, persona()) if c.type in ("repo_readme", "repo_code")]
        if not chunks:
            raise ResourceError(f"repo {repo_id} not found")
        return "\n\n".join(f"### {c.title}\n```\n{c.text}\n```" if c.type == "repo_code" else c.text for c in chunks)
