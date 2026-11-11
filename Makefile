.PHONY: install data gigsim mcp-http api test lint eval docs

install:
	uv sync

# Rebuild the GigSim world from the Kaggle CSVs in data/raw/kaggle (see docs/DATA_CARD.md)
data:
	uv run python -m scripts.data.preprocess
	uv run python -m scripts.data.generate_synthetic

gigsim:
	uv run uvicorn gigsim.app:app --port 8081

# All three MCP servers over Streamable HTTP (Ctrl+C stops all)
mcp-http:
	uv run python -m mcp_servers.marketplace.server --http --port 8101 & \
	uv run python -m mcp_servers.portfolio.server --http --port 8102 & \
	uv run python -m mcp_servers.workspace.server --http --port 8103 & \
	wait

api:
	uv run uvicorn apps.api.main:app --reload --port 8000

test:
	uv run pytest -q

lint:
	uv run ruff check .

eval:
	uv run python -m evals.runners.run_demo_eval

# Regenerate docs/TOOLS.md from the MCP schema snapshots
docs:
	UPDATE_SNAPSHOTS=1 uv run pytest -q tests/contract
	uv run python -m scripts.gen_tools_doc
