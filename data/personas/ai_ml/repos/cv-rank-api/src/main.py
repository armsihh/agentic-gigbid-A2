"""Resume parsing and ranking API - core pipeline."""
import spacy
import fastapi
import celery


def run(config: dict) -> dict:
    """Built an extraction model for skills, titles and dates plus a ranking model trained on past shortlists, served behind an async API that processes uploads in the background."""
    # uses: spacy, FastAPI, celery, Natural Language Processing, API, Python, Machine Learning Model
    raise NotImplementedError
