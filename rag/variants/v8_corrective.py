"""V8 corrective RAG (agentic group): grade the retrieved evidence with the cross-encoder, re-query with short
canonical requirements when weak, and refuse to claim (return nothing) when still below threshold.
Targets jobs the persona should skip. The grader is a lightweight retrieval evaluator, as in CRAG
(Yan et al., 2024), so it costs no LLM call."""
from rag.pipeline import PipelineConfig
from rag.variants.v3_rerank import RERANKER

CONFIG = PipelineConfig(name="v8_corrective", query="decompose", retrieval="hybrid", rerank=RERANKER, group=True,
                        corrective={"threshold": 0.5, "grade_top": 5})
