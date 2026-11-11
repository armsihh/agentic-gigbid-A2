"""Dense embeddings (fastembed / ONNX, CPU) with an on-disk cache, plus a cosine index."""
from __future__ import annotations

import hashlib
import os
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


@lru_cache(maxsize=4)
def _model(name: str):
    from fastembed import TextEmbedding
    return TextEmbedding(model_name=name)


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
    """Cross-encoder reranker with a (query, doc) score cache."""

    def __init__(self, model: str = "Xenova/ms-marco-MiniLM-L-6-v2"):
        self.model = model
        self._cache: dict[tuple[str, str], float] = {}

    def score(self, query: str, docs: list[str]) -> list[float]:
        todo = [d for d in docs if (query, d) not in self._cache]
        if todo:
            for d, s in zip(todo, _reranker(self.model).rerank(query, todo, batch_size=32)):
                self._cache[(query, d)] = float(s)
        return [self._cache[(query, d)] for d in docs]
