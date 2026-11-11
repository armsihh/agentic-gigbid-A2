"""V1 requirement decomposition (query group, required): one retrieval per extracted requirement, merged
with reciprocal rank fusion. Targets jobs that ask for several different things."""
from rag.pipeline import PipelineConfig

CONFIG = PipelineConfig(name="v1_decompose", query="decompose", retrieval="dense")
