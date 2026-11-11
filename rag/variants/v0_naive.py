"""V0 baseline (required): fixed 600-char chunks, one dense query with the whole job post, top-k cosine."""
from rag.pipeline import PipelineConfig

CONFIG = PipelineConfig(name="v0_naive", chunking="fixed", query="whole", retrieval="dense")
