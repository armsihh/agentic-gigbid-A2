"""Portfolio ingestion (B1): load a persona folder into evidence chunks with metadata.

Folder layout (data/personas/<persona>/, or any user's own portfolio folder):
  profile.json, cv.md, case_studies/*.md (JSON front-matter), repos/<name>/{README.md, src/**, requirements.txt},
  reviews.jsonl, past_proposals.jsonl
Every chunk carries: persona, type, item_id, project, skills, date, client_industry, outcome (proposals), source.

Code is ingested from local repo folders here; `rag/ingest/github.py` pulls the same layout from GitHub
through the GitHub MCP server. Incremental re-index: `load_persona` hashes each file, and callers
re-embed only chunks whose `content_hash` changed.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

EvidenceType = Literal["case_study", "repo_readme", "repo_code", "cv", "review", "past_proposal", "profile"]
CODE_SUFFIXES = {".py", ".ts", ".tsx", ".js", ".sql", ".ipynb", ".r", ".txt", ".toml", ".yaml", ".yml"}


class Chunk(BaseModel):
    chunk_id: str
    item_id: str = Field(description="The portfolio item (case study, repo, proposal...) this chunk belongs to")
    persona: str
    type: EvidenceType
    project: str | None = None
    title: str
    text: str
    source: str
    date: str | None = None
    skills: list[str] = Field(default_factory=list)
    client_industry: str | None = None
    outcome: Literal["won", "replied", "ignored"] | None = None
    style: str | None = None
    content_hash: str = ""


def _hash(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]


def _front_matter(raw: str) -> tuple[dict, str]:
    if raw.startswith("---\n"):
        _, fm, body = raw.split("---\n", 2)
        return json.loads(fm), body
    return {}, raw


def _sections(md: str) -> list[tuple[str, str]]:
    """Split markdown on '## ' headings, keeping the title block as the first section."""
    parts = re.split(r"\n(?=## )", md.strip())
    out = []
    for p in parts:
        head = p.splitlines()[0].lstrip("# ").strip()
        out.append((head, p.strip()))
    return out


def load_persona(folder: str | Path) -> list[Chunk]:
    folder = Path(folder)
    persona = folder.name
    chunks: list[Chunk] = []

    def add(**kw) -> None:
        kw.setdefault("persona", persona)
        kw["content_hash"] = _hash(kw["text"])
        chunks.append(Chunk(**kw))

    # project titles from case studies, so CV lines can be linked to the project they describe
    title_to_project: dict[str, str] = {}
    for f in (folder / "case_studies").glob("*.md"):
        fm, body = _front_matter(f.read_text(encoding="utf-8"))
        title_to_project[body.strip().splitlines()[0].lstrip("# ").strip().lower()] = fm.get("project")

    # CV: one chunk per bullet (short, project-level lines) + header block
    cv = folder / "cv.md"
    if cv.exists():
        lines = cv.read_text(encoding="utf-8").splitlines()
        header = "\n".join(line for line in lines if not line.startswith("- "))
        add(chunk_id=f"{persona}-cv-header", item_id=f"{persona}-cv", type="cv", title="CV", text=header,
            source=str(cv))
        for i, line in enumerate(x for x in lines if x.startswith("- ")):
            proj = next((p for t, p in title_to_project.items() if t in line.lower()), None)
            add(chunk_id=f"{persona}-cv-{i:02d}", item_id=f"{persona}-cv", type="cv", title="CV entry",
                text=line[2:], source=str(cv), date=line[2:6] if line[2:6].isdigit() else None, project=proj)

    # Case studies: one chunk per section, each prefixed with the title so it stands alone
    for f in sorted((folder / "case_studies").glob("*.md")):
        fm, body = _front_matter(f.read_text(encoding="utf-8"))
        title = body.strip().splitlines()[0].lstrip("# ").strip()
        for j, (head, text) in enumerate(_sections(body)):
            add(chunk_id=f"{fm['id']}#{j}", item_id=fm["id"], type="case_study", project=fm.get("project"),
                title=title, text=text if j == 0 else f"{title} - {text}", source=str(f), date=fm.get("date"),
                skills=fm.get("skills", []), client_industry=fm.get("client_industry"))

    # Repos: README and each code/config file as separate chunks of the same item
    for repo in sorted(p for p in (folder / "repos").glob("*") if p.is_dir()):
        readme = repo / "README.md"
        fm, body = _front_matter(readme.read_text(encoding="utf-8")) if readme.exists() else ({}, "")
        item = fm.get("id", f"{persona}-repo-{repo.name}")
        if body:
            add(chunk_id=f"{item}#readme", item_id=item, type="repo_readme", project=fm.get("project"),
                title=f"Repository {repo.name}", text=body, source=str(readme), date=fm.get("date"))
        for code in sorted(repo.rglob("*")):
            if code.is_file() and code.suffix.lower() in CODE_SUFFIXES:
                rel = code.relative_to(repo).as_posix()
                add(chunk_id=f"{item}#{rel}", item_id=item, type="repo_code", project=fm.get("project"),
                    title=f"{repo.name}/{rel}", text=code.read_text(encoding="utf-8")[:4000], source=str(code),
                    date=fm.get("date"))

    for name, typ in (("reviews.jsonl", "review"), ("past_proposals.jsonl", "past_proposal")):
        p = folder / name
        if not p.exists():
            continue
        for line in p.read_text(encoding="utf-8").split("\n"):
            if not line.strip():
                continue
            r = json.loads(line)
            title = f"Client review ({r.get('client_industry')})" if typ == "review" else f"Proposal: {r.get('job_title')}"
            add(chunk_id=r["id"], item_id=r["id"], type=typ, project=r.get("project"), title=title, text=r["text"],
                source=str(p), date=r.get("date"), client_industry=r.get("client_industry"),
                outcome=r.get("outcome"), style=r.get("style"), skills=r.get("job_skills", []))
    return chunks


def load_corpus(root: str | Path, personas: list[str] | None = None) -> list[Chunk]:
    root = Path(root)
    out: list[Chunk] = []
    for d in sorted(p for p in root.iterdir() if p.is_dir()):
        if personas is None or d.name in personas:
            out.extend(load_persona(d))
    return out


def load_profile(folder: str | Path) -> dict:
    p = Path(folder) / "profile.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
