"""V4 outcome-aware ranking: boost evidence from projects (and phrasing from past proposals) that won or
got replies, using a smoothed per-project outcome rate learned from past proposals."""
from rag.pipeline import PipelineConfig
from rag.variants.v3_rerank import RERANKER

CONFIG = PipelineConfig(name="v4_outcome", query="decompose", retrieval="hybrid", rerank=RERANKER, outcome=1.0)
