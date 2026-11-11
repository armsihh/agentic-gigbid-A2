"""RAG variants. Each module defines CONFIG (a PipelineConfig preset); `build_variant` builds the pipeline.

    build_variant("v2_hybrid", chunks)              # preset
    build_variant("v5_multivector", chunks, rerank=None)   # ablation: one stage flipped
"""
from __future__ import annotations

import dataclasses
import importlib

from rag.pipeline import PipelineConfig, RetrievalPipeline

VARIANTS = ["v0_naive", "v1_decompose", "v2_hybrid", "v3_rerank", "v4_outcome", "v5_multivector", "v8_corrective"]


def get_config(name: str, **overrides) -> PipelineConfig:
    cfg: PipelineConfig = importlib.import_module(f"rag.variants.{name}").CONFIG
    return dataclasses.replace(cfg, **overrides) if overrides else cfg


def build_variant(name: str, chunks, requirement_extractor=None, **overrides) -> RetrievalPipeline:
    return RetrievalPipeline(get_config(name, **overrides), chunks, requirement_extractor)
