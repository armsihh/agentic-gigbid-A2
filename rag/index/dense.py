"""Dense embeddings (fastembed / ONNX, CPU) with an on-disk cache, plus a cosine index."""
from __future__ import annotations

import hashlib
import os
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
CACHE = Path(os.environ.get("EMB_CACHE_DIR", ROOT / "data" / "processed" / "emb_cache"))

# Query/document prefixes some models were trained with
PREFIX = {
    "nomic-ai/nomic-embed-text-v1.5": ("search_query: ", "search_document: "),
    "BAAI/bge-small-en-v1.5": ("Represent this sentence for searching relevant passages: ", ""),
    "BAAI/bge-base-en-v1.5": ("Represent this sentence for searching relevant passages: ", ""),
}


LOW_MEMORY = os.environ.get("EMBED_LOW_MEMORY") == "1"


@contextmanager
def _extended_graph_optimisation():
    """fastembed hard-codes ORT_ENABLE_ALL, whose layout transforms keep extra weight copies. EXTENDED gives the same
    vectors (identical to 4 decimals) for ~43 MB less. Only used on the 512 MB host (EMBED_LOW_MEMORY=1)."""
    import onnxruntime as ort
    orig = ort.InferenceSession.__init__

    def init(self, path_or_bytes, sess_options=None, *a, **k):
        if sess_options is not None:
            sess_options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_EXTENDED
        orig(self, path_or_bytes, sess_options, *a, **k)
    ort.InferenceSession.__init__ = init
    try:
        yield
    finally:
        ort.InferenceSession.__init__ = orig


@lru_cache(maxsize=4)
def _model(name: str):
    from fastembed import TextEmbedding
    if not LOW_MEMORY:
        return TextEmbedding(model_name=name)
    # 512 MB host: no memory arena (it kept every batch's peak allocation: +250 MB live), one thread, EXTENDED graph.
    # Measured: load 80 MB instead of 123 MB, and memory returns to baseline after each batch.
    with _extended_graph_optimisation():
        return TextEmbedding(model_name=name, threads=1, enable_cpu_mem_arena=False)


class Embedder:
    def __init__(self, model: str = "BAAI/bge-small-en-v1.5"):
        self.model = model
        self.q_prefix, self.d_prefix = PREFIX.get(model, ("", ""))
        self.dir = CACHE / model.replace("/", "__")
        self.dir.mkdir(parents=True, exist_ok=True)

    def _embed(self, texts: list[str]) -> np.ndarray:
        keys = [hashlib.sha1(t.encode("utf-8")).hexdigest() for t in texts]
        out: list[np.ndarray | None] = [None] * len(texts)
        todo = []
        for i, k in enumerate(keys):
            p = self.dir / f"{k}.npy"
            if p.exists():
                out[i] = np.load(p)
            else:
                todo.append(i)
        if todo:
            vecs = list(_model(self.model).embed([texts[i] for i in todo], batch_size=64))
            for i, v in zip(todo, vecs):
                v = np.asarray(v, dtype=np.float32)
                v /= np.linalg.norm(v) + 1e-12
                np.save(self.dir / f"{keys[i]}.npy", v)
                out[i] = v
        return np.vstack(out) if out else np.zeros((0, 0), dtype=np.float32)

    def docs(self, texts: list[str]) -> np.ndarray:
        return self._embed([self.d_prefix + t for t in texts])

    def queries(self, texts: list[str]) -> np.ndarray:
        return self._embed([self.q_prefix + t for t in texts])


class DenseIndex:
    def __init__(self, texts: list[str], embedder: Embedder):
        self.embedder = embedder
        self.matrix = embedder.docs(texts) if texts else np.zeros((0, 1), dtype=np.float32)

    def scores(self, query: str) -> np.ndarray:
        q = self.embedder.queries([query])[0]
        return self.matrix @ q

    def scores_many(self, queries: list[str]) -> np.ndarray:
        return self.embedder.queries(queries) @ self.matrix.T


@lru_cache(maxsize=2)
def _reranker(name: str):
    from fastembed.rerank.cross_encoder import TextCrossEncoder
    return TextCrossEncoder(model_name=name)


class Reranker:
    """Cross-encoder reranker with a (query, doc) score cache.

    Memory: ONNX activations grow with batch x sequence length. 32 full 512-token chunks took ~350 MB on top of the
    model, which OOM-killed the 512 MB production container at the claim verifier. Production builds it with
    batch_size=1, max_chars=600 (~15 MB, same claims removed); offline evals keep the defaults so their numbers are unchanged."""

    def __init__(self, model: str = "Xenova/ms-marco-MiniLM-L-6-v2", batch_size: int = 32, max_chars: int | None = None):
        self.model = model
        self.batch_size, self.max_chars = batch_size, max_chars
        self._cache: dict[tuple[str, str], float] = {}

    def score(self, query: str, docs: list[str]) -> list[float]:
        todo = [d for d in docs if (query, d) not in self._cache]
        if todo:
            inputs = [d[: self.max_chars] for d in todo] if self.max_chars else todo
            for d, s in zip(todo, _reranker(self.model).rerank(query, inputs, batch_size=self.batch_size)):
                self._cache[(query, d)] = float(s)
        return [self._cache[(query, d)] for d in docs]


class EmbeddingRelevance:
    """Drop-in for Reranker.score() that reuses the bi-encoder the dense index already loaded, so the claim verifier
    adds no model (the cross-encoder costs ~137 MB, which pushed the 512 MB free host over its limit at `verify`).
    Cosine is mapped to a logit so ClaimVerifier's sigmoid thresholds (0.6 / 0.3) keep their meaning. Calibrated
    against the cross-encoder on 106 claim/evidence pairs from the personas (source chunk removed): 92.5% label
    agreement; unrelated evidence rejected 98% (cross-encoder 100%). Hard facts (numbers, tools) are checked
    lexically either way, so a wrong number is still always removed."""

    MID, SLOPE = 0.6787, 35.79

    def __init__(self, embedder: Embedder | None = None, max_chars: int = 600):
        self.embedder = embedder or Embedder()
        self.max_chars = max_chars

    def score(self, query: str, docs: list[str]) -> list[float]:
        if not docs:
            return []
        q = self.embedder.queries([query])[0]
        d = self.embedder.docs([t[: self.max_chars] for t in docs])
        return [float((c - self.MID) * self.SLOPE) for c in d @ q]
