"""API settings: environment variables only (secrets never in code or the repo)."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")

    app_env: str = "development"
    app_secret_key: str = "dev-only-change-me"
    database_url: str = f"sqlite:///{(ROOT / 'data' / 'app.db').as_posix()}"
    checkpoint_url: str | None = None          # postgres://... in docker/deploy; default: sqlite file next to app.db
    redis_url: str | None = None               # set -> runs go to the Arq worker; unset -> in-process runner
    marketplace_mode: str = "gigsim"
    gigsim_base_url: str = "http://localhost:8081"
    gigsim_admin_token: str = "dev-admin"
    web_origin: str = "http://localhost:5173"
    serve_web_dir: str | None = None           # path to the built React app (single-container deploy)
    reviewer_email: str = "reviewer@gigbid.dev"
    reviewer_password: str | None = None       # seeded reviewer account (password from env, never committed)
    session_hours: int = 72

    @property
    def is_postgres(self) -> bool:
        return self.database_url.startswith("postgres")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
