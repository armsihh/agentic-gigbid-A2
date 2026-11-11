"""Portfolio MCP server through an in-memory MCP client session (A7)."""
from __future__ import annotations

import shutil
import time

import pytest
from mcp.shared.memory import create_connected_server_and_client_session as connect

from mcp_servers.common import ROOT
from mcp_servers.portfolio.server import build_server
from mcp_servers.portfolio.tools import PortfolioStore
from rag.retriever import EvidenceFilters


@pytest.fixture
def server(monkeypatch, audit_dir):
    monkeypatch.setenv("PORTFOLIO_PERSONA", "ai_ml")
    return build_server(PortfolioStore(variant="bm25"))._mcp_server


async def test_surface(server):
    async with connect(server) as s:
        tools = (await s.list_tools()).tools
        templates = {r.uriTemplate for r in (await s.list_resource_templates()).resourceTemplates}
        prompts = (await s.list_prompts()).prompts
    assert {t.name for t in tools} == {"search_evidence", "get_case_study", "list_skills"}
    assert all(t.annotations.readOnlyHint and t.outputSchema for t in tools)
    assert {"portfolio://case/{case_id}", "portfolio://proposal/{proposal_id}"} <= templates
    assert len(prompts) >= 3


async def test_search_returns_typed_dated_evidence_scoped_to_persona(server):
    async with connect(server) as s:
        r = await s.call_tool("search_evidence", {"requirement": "support ticket classification", "k": 5})
    items = r.structuredContent["items"]
    assert items and all(i["evidence_id"].startswith("ai_ml-") for i in items)
    assert {"type", "source", "date", "outcome"} <= set(items[0])


async def test_filters_outcome_and_type(server):
    async with connect(server) as s:
        r = await s.call_tool("search_evidence", {"requirement": "chatbot", "types": ["past_proposal"],
                                                  "outcome": ["won"], "k": 5})
    items = r.structuredContent["items"]
    assert items and all(i["type"] == "past_proposal" and i["outcome"] == "won" for i in items)


async def test_case_study_and_resources(server):
    async with connect(server) as s:
        r = await s.call_tool("get_case_study", {"id": "rag-legal"})
        res = await s.read_resource("portfolio://case/ai_ml-cs-ticket-triage")
        missing = await s.call_tool("get_case_study", {"id": "nope"})
    assert r.structuredContent["id"] == "ai_ml-cs-rag-legal"
    assert "ai_ml-repo-contract-qa" in r.structuredContent["related_items"]
    assert "Support ticket triage" in res.contents[0].text
    assert missing.isError and "[not_found]" in missing.content[0].text


def test_incremental_reindex_picks_up_new_work(tmp_path):
    root = tmp_path / "personas"
    shutil.copytree(ROOT / "data" / "personas" / "ai_ml", root / "ai_ml")
    store = PortfolioStore(root=root, variant="bm25")
    assert not store.search("quantum annealing scheduler", 3, EvidenceFilters()).items
    time.sleep(0.05)
    (root / "ai_ml" / "case_studies" / "ai_ml-cs-new.md").write_text(
        '---\n{"id": "ai_ml-cs-new", "type": "case_study", "persona": "ai_ml", "project": "new", '
        '"skills": ["Optimization"], "date": "2026-11-01", "client_industry": "Energy"}\n---\n'
        "# Quantum annealing scheduler\n\n## What I did\nBuilt a quantum annealing scheduler.\n", encoding="utf-8")
    hits = store.search("quantum annealing scheduler", 3, EvidenceFilters()).items
    assert hits and hits[0].item_id == "ai_ml-cs-new"


def test_implied_skills_survive_in_repo_code():
    """Guard: the corpus hides some skills ONLY in code imports (e.g. Celery). A formatter once stripped them
    as 'unused imports'; data/ is excluded from ruff, and this test fails if that evidence disappears."""
    store = PortfolioStore(variant="bm25")
    code = [c for c in store.chunks if c.chunk_id == "ai_ml-repo-cv-rank-api#src/main.py"]
    assert code and "import celery" in code[0].text
    case = [c for c in store.chunks if c.item_id == "ai_ml-cs-resume-parser"]
    assert case and not any("celery" in c.text.lower() for c in case)  # never named in the case study
