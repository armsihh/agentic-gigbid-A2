"""Retriever interface + factory. The variant is chosen by config (agent/config.yaml: rag.variant),
never hard-coded, so the shipped design is whatever the evaluation picked (R6).

Variants live in rag/variants/. Until Part B lands, the factory offers `bm25` (lexical baseline).
"""
from __future__ import annotations

import re
from typing import Any, Protocol

from pydantic import BaseModel, Field
from rank_bm25 import BM25Okapi

from rag.ingest.loaders import Chunk


class EvidenceFilters(BaseModel):
    persona: str | None = None
    types: list[str] | None = Field(None, description="e.g. case_study, repo_code, past_proposal")
    outcome: list[str] | None = Field(None, description="past proposals only: won, replied, ignored")
    project: str | None = None
    since: str | None = Field(None, description="ISO date; only evidence dated on/after")


class ScoredChunk(BaseModel):
    chunk: Chunk
    score: float


class Retriever(Protocol):
    name: str

    def search(self, query: str, k: int = 5, filters: EvidenceFilters | None = None) -> list[ScoredChunk]: ...


TOKEN = re.compile(r"[a-z0-9][a-z0-9+#.\-]*")


def tokenize(text: str) -> list[str]:
    return [t.strip(".-") for t in TOKEN.findall(text.lower()) if len(t.strip(".-")) > 1]


def passes(c: Chunk, f: EvidenceFilters | None) -> bool:
    if f is None:
        return True
    return ((f.persona is None or c.persona == f.persona) and (f.types is None or c.type in f.types)
            and (f.outcome is None or c.outcome in f.outcome) and (f.project is None or c.project == f.project)
            and (f.since is None or (c.date or "") >= f.since))


class BM25Retriever:
    name = "bm25"

    def __init__(self, chunks: list[Chunk]):
        self.chunks = chunks
        self.bm25 = BM25Okapi([tokenize(f"{c.title} {c.text} {' '.join(c.skills)}") for c in chunks])

    def search(self, query: str, k: int = 5, filters: EvidenceFilters | None = None) -> list[ScoredChunk]:
        scores = self.bm25.get_scores(tokenize(query))
        ranked = sorted(((s, c) for s, c in zip(scores, self.chunks) if passes(c, filters)),
                        key=lambda x: x[0], reverse=True)
        return [ScoredChunk(chunk=c, score=float(s)) for s, c in ranked[:k] if s > 0]


def get_retriever(chunks: list[Chunk], variant: str | None = None, **kwargs: Any) -> Retriever:
    variant = variant or "bm25"
    if variant == "bm25":
        return BM25Retriever(chunks)
    from rag.variants import build_variant  # Part B variants (v0..v9)
    return build_variant(variant, chunks, **kwargs)
