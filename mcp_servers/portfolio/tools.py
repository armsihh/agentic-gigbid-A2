"""Portfolio store: loads a portfolio folder, keeps the retriever index fresh, answers lookups."""
from __future__ import annotations

import os
import threading
from collections import defaultdict
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from rag.ingest.loaders import Chunk, load_corpus, load_profile
from rag.retriever import EvidenceFilters, Retriever, get_retriever

ROOT = Path(__file__).resolve().parents[2]
TYPE_LABEL = {"case_study": "case study", "repo_readme": "repository README", "repo_code": "repository code",
              "cv": "CV", "review": "client review", "past_proposal": "past proposal", "profile": "profile"}


class EvidenceItem(BaseModel):
    evidence_id: str = Field(description="Chunk id; cite this in proposals")
    item_id: str = Field(description="Portfolio item the chunk belongs to (case study, repo, proposal...)")
    type: str
    source: str = Field(description="Human-readable source, e.g. 'case study: Support ticket triage classifier'")
    title: str
    date: str | None = None
    outcome: str | None = Field(None, description="won / replied / ignored, for past proposals")
    project: str | None = None
    client_industry: str | None = None
    skills: list[str] = Field(default_factory=list)
    text: str
    score: float | None = None


class EvidenceResults(BaseModel):
    requirement: str
    retriever: str
    items: list[EvidenceItem]


class CaseStudy(BaseModel):
    id: str
    project: str | None
    title: str
    date: str | None
    client_industry: str | None
    skills: list[str]
    markdown: str
    related_items: list[str] = Field(description="Other items about the same project (repo, reviews, proposals)")


class SkillEntry(BaseModel):
    skill: str
    evidence_count: int
    projects: list[str]


class SkillList(BaseModel):
    persona: str | None
    skills: list[SkillEntry]


def to_item(c: Chunk, score: float | None = None) -> EvidenceItem:
    return EvidenceItem(evidence_id=c.chunk_id, item_id=c.item_id, type=c.type,
                        source=f"{TYPE_LABEL.get(c.type, c.type)}: {c.title}", title=c.title, date=c.date,
                        outcome=c.outcome, project=c.project, client_industry=c.client_industry, skills=c.skills,
                        text=c.text, score=round(score, 4) if score is not None else None)


class PortfolioStore:
    def __init__(self, root: str | Path | None = None, variant: str | None = None):
        self.root = Path(root or os.environ.get("PORTFOLIO_DIR", ROOT / "data" / "personas"))
        if not self.root.is_dir():
            raise SystemExit(f"Portfolio folder not found: {self.root}. Set PORTFOLIO_DIR to a folder containing one "
                             "sub-folder per freelancer (see mcp_servers/portfolio/README.md for the layout).")
        self.variant = variant or os.environ.get("RAG_VARIANT") or _config_variant()
        self._lock = threading.Lock()
        self._mtime = -1.0
        self.chunks: list[Chunk] = []
        self.retriever: Retriever | None = None
        self.refresh()

    def _latest_mtime(self) -> float:
        return max((p.stat().st_mtime for p in self.root.rglob("*") if p.is_file()), default=0.0)

    def refresh(self) -> bool:
        """Re-index when files changed (the UI writes new work into the folder). Cheap mtime check."""
        m = self._latest_mtime()
        if m == self._mtime:
            return False
        with self._lock:
            self.chunks = load_corpus(self.root)
            self.by_id = {c.chunk_id: c for c in self.chunks}
            self.by_item: dict[str, list[Chunk]] = defaultdict(list)
            for c in self.chunks:
                self.by_item[c.item_id].append(c)
            self.retriever = get_retriever(self.chunks, self.variant)
            self._mtime = m
        return True

    # ------------------------------------------------------------- operations
    def search(self, requirement: str, k: int, filters: EvidenceFilters) -> EvidenceResults:
        self.refresh()
        hits = self.retriever.search(requirement, k=k, filters=filters)
        return EvidenceResults(requirement=requirement, retriever=self.retriever.name,
                               items=[to_item(h.chunk, h.score) for h in hits])

    def item(self, item_id: str, persona: str | None) -> list[Chunk]:
        self.refresh()
        chunks = self.by_item.get(item_id) or ([self.by_id[item_id]] if item_id in self.by_id else [])
        return [c for c in chunks if persona is None or c.persona == persona]

    def case_study(self, cid: str, persona: str | None) -> CaseStudy | None:
        self.refresh()
        chunks = self.item(cid, persona)
        if not chunks:  # allow lookup by project slug
            chunks = [c for c in self.chunks if c.type == "case_study" and c.project == cid
                      and (persona is None or c.persona == persona)]
        chunks = [c for c in chunks if c.type == "case_study"]
        if not chunks:
            return None
        first = chunks[0]
        md = Path(first.source).read_text(encoding="utf-8").split("---\n", 2)[-1]
        related = sorted({c.item_id for c in self.chunks if c.project == first.project and c.item_id != first.item_id
                          and c.persona == first.persona})
        return CaseStudy(id=first.item_id, project=first.project, title=first.title, date=first.date,
                         client_industry=first.client_industry, skills=first.skills, markdown=md.strip(),
                         related_items=related)

    def skills(self, persona: str | None) -> SkillList:
        self.refresh()
        counts: dict[str, set[str]] = defaultdict(set)
        projects: dict[str, set[str]] = defaultdict(set)
        for c in self.chunks:
            if (persona and c.persona != persona) or c.type not in ("case_study",):
                continue
            for s in c.skills:
                counts[s].add(c.item_id)
                if c.project:
                    projects[s].add(c.project)
        prof_skills = []
        for d in self.root.iterdir():
            if d.is_dir() and (persona is None or d.name == persona):
                prof_skills += load_profile(d).get("skills", [])
        for s in prof_skills:
            counts.setdefault(s, set())
        entries = [SkillEntry(skill=s, evidence_count=len(ids), projects=sorted(projects.get(s, set())))
                   for s, ids in counts.items()]
        entries.sort(key=lambda e: (-e.evidence_count, e.skill))
        return SkillList(persona=persona, skills=entries)

    def profile(self, persona: str | None) -> dict:
        if persona:
            return load_profile(self.root / persona)
        return {d.name: load_profile(d) for d in self.root.iterdir() if d.is_dir()}


def _config_variant() -> str:
    try:
        cfg = yaml.safe_load((ROOT / "agent" / "config.yaml").read_text())
        return (cfg.get("rag") or {}).get("variant", "bm25")
    except FileNotFoundError:
        return "bm25"
