"""Composable retrieval pipeline. Every RAG variant (rag/variants/vN_*.py) is a preset of these stages,
so ablations flip exactly one stage and one command reruns the full comparison.

Stages
  chunking   structured (loader chunks: sections, README, code files) | fixed (600-char windows, V0)
  query      whole (entire job post) | decompose (one query per requirement, merged with RRF)
  retrieval  dense | bm25 | hybrid (BM25 + dense, reciprocal rank fusion)
  rerank     cross-encoder model name or None
  outcome    weight of the outcome-aware boost (projects/phrasing that won or got replies), 0 = off
  group      return one item per project, scored from all of its vectors (summary, README, code...)
  corrective grade evidence, re-query when weak, refuse to claim when still weak
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from rag.index.dense import DenseIndex, Embedder, Reranker
from rag.ingest.loaders import Chunk
from rag.retriever import BM25Retriever, EvidenceFilters, ScoredChunk, passes

RRF_K = 60
OUTCOME_VALUE = {"won": 1.0, "replied": 0.6, "ignored": 0.0}


@dataclass
class PipelineConfig:
    name: str
    chunking: str = "structured"
    query: str = "whole"
    retrieval: str = "dense"
    rerank: str | None = None
    outcome: float = 0.0
    group: bool = False
    corrective: dict[str, Any] | None = None
    embedder: str = "BAAI/bge-small-en-v1.5"
    candidates: int = 30
    rerank_chars: int = 1200      # cross-encoders truncate at 512 tokens anyway
    rerank_top: int = 15
    max_query_chars: int = 2000


@dataclass
class SearchTrace:
    queries: list[str] = field(default_factory=list)
    requeried: bool = False
    refused: bool = False
    top_grade: float | None = None


def fixed_chunks(chunks: list[Chunk], size: int = 600, overlap: int = 100) -> list[Chunk]:
    """V0 baseline chunking: concatenate each item and cut fixed windows, ignoring structure."""
    by_item: dict[str, list[Chunk]] = defaultdict(list)
    for c in chunks:
        by_item[c.item_id].append(c)
    out = []
    for item, cs in by_item.items():
        text = "\n".join(c.text for c in cs)
        base = cs[0]
        for n, start in enumerate(range(0, max(1, len(text)), size - overlap)):
            piece = text[start:start + size]
            if not piece.strip():
                continue
            out.append(base.model_copy(update={"chunk_id": f"{item}@{n}", "text": piece}))
    return out


class RetrievalPipeline:
    def __init__(self, cfg: PipelineConfig, chunks: list[Chunk], requirement_extractor=None):
        self.cfg = cfg
        self.name = cfg.name
        self.chunks = fixed_chunks(chunks) if cfg.chunking == "fixed" else list(chunks)
        self.texts = [f"{c.title}\n{c.text}" for c in self.chunks]
        self.dense = DenseIndex(self.texts, Embedder(cfg.embedder)) if cfg.retrieval in ("dense", "hybrid") else None
        self.bm25 = BM25Retriever(self.chunks) if cfg.retrieval in ("bm25", "hybrid") else None
        self.reranker = Reranker(cfg.rerank) if cfg.rerank or cfg.corrective else None
        self.extract = requirement_extractor
        self.outcome_by_project = self._project_outcomes(chunks) if cfg.outcome else {}
        self.last_trace = SearchTrace()

    # ------------------------------------------------------------ helpers
    @staticmethod
    def _project_outcomes(chunks: list[Chunk]) -> dict[tuple[str, str], float]:
        """Smoothed outcome rate per (persona, project) from past proposals: what actually worked."""
        acc: dict[tuple[str, str], list[float]] = defaultdict(list)
        for c in chunks:
            if c.type == "past_proposal" and c.project and c.outcome:
                acc[(c.persona, c.project)].append(OUTCOME_VALUE[c.outcome])
        prior, strength = 0.25, 3.0
        return {k: (sum(v) + prior * strength) / (len(v) + strength) for k, v in acc.items()}

    def _mask(self, filters: EvidenceFilters | None) -> np.ndarray:
        return np.array([passes(c, filters) for c in self.chunks], dtype=bool)

    def _rank_one(self, query: str, mask: np.ndarray) -> list[tuple[int, float]]:
        """Ranked (chunk index, score) for one query, after first-stage retrieval and optional rerank."""
        n = self.cfg.candidates
        query = query[: self.cfg.max_query_chars]
        lists: list[list[int]] = []
        dense_scores = None
        if self.dense is not None:
            s = self.dense.scores(query)
            s = np.where(mask, s, -np.inf)
            dense_scores = s
            lists.append([int(i) for i in np.argsort(-s)[:n] if np.isfinite(s[i])])
        if self.bm25 is not None:
            b = np.asarray(self.bm25.bm25.get_scores(_tok(query)))
            b = np.where(mask, b, -np.inf)
            lists.append([int(i) for i in np.argsort(-b)[:n] if np.isfinite(b[i]) and b[i] > 0])
        if len(lists) == 1:
            idx = lists[0]
            base = [(i, float(dense_scores[i]) if dense_scores is not None and self.bm25 is None else 1.0 / (RRF_K + r))
                    for r, i in enumerate(idx)]
        else:
            fused: dict[int, float] = defaultdict(float)
            for lst in lists:
                for r, i in enumerate(lst):
                    fused[i] += 1.0 / (RRF_K + r + 1)
            base = sorted(fused.items(), key=lambda x: -x[1])[:n]
        return base

    def _rerank(self, ranked: list[tuple[int, float]], query: str) -> list[tuple[int, float]]:
        """Re-score the top `rerank_top` fused candidates ONCE against one compact query (not once per
        requirement: ~15 cross-encoder pairs per job instead of ~150, which matters on CPU)."""
        if not self.cfg.rerank or not ranked:
            return ranked
        head, tail = ranked[: self.cfg.rerank_top], ranked[self.cfg.rerank_top:]
        scores = self.reranker.score(query, [self.texts[i][: self.cfg.rerank_chars] for i, _ in head])
        head = sorted(((i, s) for (i, _), s in zip(head, scores)), key=lambda x: -x[1])
        floor = min(scores) - 1.0
        return head + [(i, floor - r * 1e-3) for r, (i, _) in enumerate(tail)]

    @staticmethod
    def _merge(ranked_lists: list[list[tuple[int, float]]]) -> list[tuple[int, float]]:
        if len(ranked_lists) == 1:
            return ranked_lists[0]
        fused: dict[int, float] = defaultdict(float)
        for lst in ranked_lists:
            for r, (i, _) in enumerate(lst):
                fused[i] += 1.0 / (RRF_K + r + 1)
        return sorted(fused.items(), key=lambda x: -x[1])

    def _apply_outcome(self, ranked: list[tuple[int, float]]) -> list[tuple[int, float]]:
        if not self.cfg.outcome or not ranked:
            return ranked
        # work in rank space so the boost is comparable across score scales
        out = []
        for r, (i, _) in enumerate(ranked):
            c = self.chunks[i]
            o = OUTCOME_VALUE.get(c.outcome, None) if c.type == "past_proposal" else None
            if o is None:
                o = self.outcome_by_project.get((c.persona, c.project or ""), 0.25)
            out.append((i, 1.0 / (RRF_K + r + 1) + self.cfg.outcome * o / RRF_K))
        return sorted(out, key=lambda x: -x[1])

    def _group(self, ranked: list[tuple[int, float]]) -> list[tuple[int, float]]:
        """One result per project; project score = best vector + 0.25 * next two (multi-vector evidence)."""
        if not self.cfg.group:
            return ranked
        n = len(ranked)
        rank_score = {i: (n - r) / n for r, (i, _) in enumerate(ranked)}
        per: dict[str, list[int]] = defaultdict(list)
        loose: list[int] = []
        for i, _ in ranked:
            p = self.chunks[i].project
            (per[p].append(i) if p else loose.append(i))
        scored = []
        for idxs in per.values():
            s = [rank_score[i] for i in idxs]
            scored.append((idxs[0], s[0] + 0.25 * sum(s[1:3])))
        scored += [(i, rank_score[i] * 0.9) for i in loose]
        return sorted(scored, key=lambda x: -x[1])

    # ------------------------------------------------------------ public API
    def search(self, query: str, k: int = 5, filters: EvidenceFilters | None = None) -> list[ScoredChunk]:
        """Single requirement (what the Portfolio MCP tool calls)."""
        return self._run([query], query, [query], k, filters)

    def search_job(self, job: dict, k: int = 10, filters: EvidenceFilters | None = None) -> list[ScoredChunk]:
        """Whole job (evaluation and Fit Matcher): applies the configured query strategy."""
        whole = f"{job['title']}\n{', '.join(job.get('skills') or [])}\n{job['description']}"
        compact = f"{job['title']}. Skills: {', '.join(job.get('skills') or [])}. {job['description'][:300]}"
        reqs = (self.extract or default_requirements)(job)
        queries = (reqs or [whole]) if self.cfg.query == "decompose" else [whole]
        alternate = [whole] if self.cfg.query == "decompose" else (reqs or [whole])
        return self._run(queries, compact, alternate, k, filters)

    def _retrieve(self, queries: list[str], compact: str, mask) -> list[tuple[int, float]]:
        ranked = self._merge([self._rank_one(q, mask) for q in queries])
        ranked = self._rerank(ranked, compact)
        ranked = self._apply_outcome(ranked)
        return self._group(ranked)

    def _run(self, queries: list[str], compact: str, alternate: list[str], k: int, filters) -> list[ScoredChunk]:
        trace = SearchTrace(queries=list(queries))
        mask = self._mask(filters)
        ranked = self._retrieve(queries, compact, mask)
        if self.cfg.corrective:
            ranked = self._corrective(ranked, compact, alternate, mask, trace)
        self.last_trace = trace
        return [ScoredChunk(chunk=self.chunks[i], score=float(s)) for i, s in ranked[:k]]

    def _grade(self, compact: str, idxs: list[int]) -> float:
        """Evidence grade = best cross-encoder relevance (sigmoid) of the top items to the job. Cached scores."""
        if not idxs:
            return 0.0
        s = self.reranker.score(compact, [self.texts[i][: self.cfg.rerank_chars] for i in idxs])
        return float(1 / (1 + np.exp(-max(s))))

    def _corrective(self, ranked, compact, alternate, mask, trace: SearchTrace):
        c = self.cfg.corrective
        grade = self._grade(compact, [i for i, _ in ranked[: c.get("grade_top", 5)]])
        trace.top_grade = grade
        if grade >= c["threshold"]:
            return ranked
        # weak evidence: re-query with the other query strategy (whole post <-> per-requirement)
        trace.requeried = True
        again = self._retrieve(alternate, compact, mask)
        grade2 = self._grade(compact, [i for i, _ in again[: c.get("grade_top", 5)]])
        trace.top_grade = max(grade, grade2)
        if trace.top_grade < c["threshold"]:
            trace.refused = True  # no evidence good enough: the writer must not claim this
            return []
        return again if grade2 > grade else ranked


def _tok(text: str) -> list[str]:
    from rag.retriever import tokenize
    return tokenize(text)


GENERIC_TAGS = {"english", "communication skills", "writing", "review", "google", "marketing", "website",
                "business with 1-9 employees", "consultant", "researcher", "content writing", "automation"}


def default_requirements(job: dict) -> list[str]:
    """Rule-based requirement extraction (no LLM): one query per specific skill tag, phrased in the
    job's context. The LLM Job Analyst's JobSpec.requirements replace this in the graph."""
    title = job["title"][:80]
    tags = [s for s in (job.get("skills") or []) if s.lower() not in GENERIC_TAGS]
    reqs = [f"{s} - {title}" for s in tags[:8]]
    return reqs or [title]
