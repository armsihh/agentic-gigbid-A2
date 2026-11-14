# syntax=docker/dockerfile:1
# Python services image: api, worker, gigsim and the three MCP servers (different `command` per compose service).
# Model weights and portfolio embeddings are downloaded/computed at BUILD time so containers start fast and offline.
FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy \
    PATH=/opt/venv/bin:$PATH \
    FASTEMBED_CACHE_PATH=/opt/models EMB_CACHE_DIR=/opt/emb_cache \
    APP_DATA_DIR=/app/data/runtime
COPY --from=ghcr.io/astral-sh/uv:0.11.23 /uv /usr/local/bin/uv
WORKDIR /app

# dependencies first (cached layer)
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev --no-install-project

COPY agent agent
COPY apps/api apps/api
COPY apps/__init__.py apps/__init__.py
COPY gigsim gigsim
COPY mcp_servers mcp_servers
COPY rag rag
COPY worker worker
COPY scripts scripts
COPY data/gigsim_seed data/gigsim_seed
COPY data/personas data/personas
COPY data/policy_pack data/policy_pack

# bake models + corpus embeddings for every variant the deployment may select
ARG BAKE_VARIANTS="v2_hybrid v5_multivector"
RUN python - <<'EOF'
import os
from rag.ingest.loaders import load_corpus
from rag.variants import build_variant
chunks = load_corpus("data/personas")
for v in os.environ.get("BAKE_VARIANTS", "v2_hybrid").split():
    p = build_variant(v, chunks)
    p.search("warm up the models", 3)
    print("baked", v)
EOF

RUN python -c "from rag.index.dense import Reranker; Reranker('Xenova/ms-marco-MiniLM-L-6-v2').score('warm', ['up'])"  # claim verifier model
RUN useradd -m -u 1000 gigbid && mkdir -p /app/data/runtime /app/data/audit && chown -R gigbid /app/data /opt/emb_cache /opt/models
USER gigbid
EXPOSE 8000
CMD ["uvicorn", "apps.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
