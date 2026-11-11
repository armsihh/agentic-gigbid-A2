"""V2 hybrid (retrieval group, required): BM25 + dense fused with reciprocal rank fusion. Targets exact
tool and library names ("Celery", "dbt", "Pinecone") that embeddings blur."""
from rag.pipeline import PipelineConfig

CONFIG = PipelineConfig(name="v2_hybrid", query="decompose", retrieval="hybrid")
