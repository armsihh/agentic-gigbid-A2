# syntax=docker/dockerfile:1
# Single-container deployment (Render free tier: one service, 512 MB, 0.1 CPU).
# Runs GigSim as a local subprocess and the API serving the built web UI. Postgres is external (Neon).
# Production RAG is V2 hybrid (no cross-encoder): V5 needs ~480 MB and ~10 s/search at 0.1 CPU; V2 measured
# 291 MB and ~0.1 s/search locally (docs/adr/0004-production-rag-variant.md).
FROM node:22-slim AS web
WORKDIR /web
COPY apps/web/package.json apps/web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY apps/web ./
RUN npm run build

FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PATH=/opt/venv/bin:$PATH \
    FASTEMBED_CACHE_PATH=/opt/models EMB_CACHE_DIR=/opt/emb_cache APP_DATA_DIR=/app/data/runtime \
    RAG_VARIANT=v2_hybrid VERIFIER_RELEVANCE=embedding EMBED_LOW_MEMORY=1 MAX_CONCURRENT_RUNS=1 SERVE_WEB_DIR=/app/web GIGSIM_BASE_URL=http://127.0.0.1:8081 \
    OMP_NUM_THREADS=1 MALLOC_ARENA_MAX=2
COPY --from=ghcr.io/astral-sh/uv:0.11.23 /uv /usr/local/bin/uv
WORKDIR /app
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
RUN python -c "from rag.ingest.loaders import load_corpus; from rag.variants import build_variant; \
p = build_variant('v2_hybrid', load_corpus('data/personas')); p.search('warm up', 3); print('baked v2')"
COPY --from=web /web/dist /app/web
COPY infra/docker/start-all-in-one.sh /app/start.sh
RUN python -c "from rag.index.dense import Reranker; Reranker('Xenova/ms-marco-MiniLM-L-6-v2').score('warm', ['up'])"  # claim verifier model
RUN useradd -m -u 1000 gigbid && mkdir -p /app/data/runtime /app/data/audit && chown -R gigbid /app/data /opt/emb_cache /opt/models \
    && chmod +x /app/start.sh
USER gigbid
EXPOSE 8000
CMD ["/app/start.sh"]
