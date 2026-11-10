.PHONY: install data gigsim api test lint eval

install:
	uv sync

# Rebuild the GigSim world from the Kaggle CSVs in data/raw/kaggle (see docs/DATA_CARD.md)
data:
	uv run python -m scripts.data.preprocess
	uv run python -m scripts.data.generate_synthetic

gigsim:
	uv run uvicorn gigsim.app:app --port 8081

api:
	uv run uvicorn apps.api.main:app --reload --port 8000

test:
	uv run pytest -q

lint:
	uv run ruff check .

eval:
	uv run python -m evals.runners.run_demo_eval
