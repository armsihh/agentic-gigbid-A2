"""V5 multi-vector items: case-study sections, README and code are indexed as separate vectors and returned
as one project, scored from all of its vectors. Targets repos that look irrelevant from the README alone."""
from rag.pipeline import PipelineConfig
from rag.variants.v3_rerank import RERANKER

CONFIG = PipelineConfig(name="v5_multivector", query="decompose", retrieval="hybrid", rerank=RERANKER, group=True)
