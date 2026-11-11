"""V3 cross-encoder reranking (retrieval group, required): hybrid candidates re-scored by a cross-encoder.
Targets precision at small k."""
from rag.pipeline import PipelineConfig

RERANKER = "Xenova/ms-marco-MiniLM-L-6-v2"
CONFIG = PipelineConfig(name="v3_rerank", query="decompose", retrieval="hybrid", rerank=RERANKER)
