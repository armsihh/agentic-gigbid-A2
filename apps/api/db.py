"""Relational data (users, settings, job index, runs, outcomes). Graph state lives in the LangGraph
checkpointer; this DB holds projections for fast listing (inbox, pipeline, analytics) and user settings.
Every query is scoped by user_id (tenant isolation, E4)."""
from __future__ import annotations

import datetime as dt
import json
from typing import Any

from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
    select,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from apps.api.settings import get_settings


class Base(DeclarativeBase):
    pass


def now() -> dt.datetime:
    return dt.datetime.now(dt.UTC).replace(tzinfo=None)


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(256))
    persona: Mapped[str] = mapped_column(String(64), default="ai_ml")
    marketplace: Mapped[str] = mapped_column(String(32), default="gigsim")      # gigsim | upwork
    settings: Mapped[dict] = mapped_column(JSON, default=dict)                 # rates, budgets, autonomy, filters
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now)


class SavedSearch(Base):
    __tablename__ = "saved_searches"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    query: Mapped[dict] = mapped_column(JSON, default=dict)                    # search_jobs arguments
    interval_minutes: Mapped[int] = mapped_column(Integer, default=60)
    last_run_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    last_posted_at: Mapped[str | None] = mapped_column(String(40), nullable=True)


class JobRecord(Base):
    """Inbox / pipeline projection of a bid-graph thread."""
    __tablename__ = "jobs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    job_id: Mapped[str] = mapped_column(String(64), index=True)
    thread_id: Mapped[str] = mapped_column(String(128), unique=True)
    title: Mapped[str] = mapped_column(String(300))
    category: Mapped[str | None] = mapped_column(String(40), nullable=True)
    status: Mapped[str] = mapped_column(String(40), default="queued")         # graph status or halt reason
    stage: Mapped[str] = mapped_column(String(20), default="inbox")           # pipeline: drafted ... hired/lost
    action: Mapped[str | None] = mapped_column(String(10), nullable=True)      # bid / watch / skip
    fit: Mapped[float | None] = mapped_column(Float, nullable=True)
    risk: Mapped[float | None] = mapped_column(Float, nullable=True)
    risk_level: Mapped[str | None] = mapped_column(String(10), nullable=True)
    price: Mapped[float | None] = mapped_column(Float, nullable=True)
    connects_cost: Mapped[int | None] = mapped_column(Integer, nullable=True)
    proposal_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    marketplace_thread_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    summary: Mapped[dict] = mapped_column(JSON, default=dict)                 # reasons, flags (small)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now, onupdate=now)


class RunRecord(Base):
    __tablename__ = "runs"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    thread_id: Mapped[str] = mapped_column(String(128), index=True)
    kind: Mapped[str] = mapped_column(String(20))                              # bid | conversation | resume
    status: Mapped[str] = mapped_column(String(30), default="queued")
    trace_id: Mapped[str] = mapped_column(String(64))
    started_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now)
    finished_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    latency_s: Mapped[float | None] = mapped_column(Float, nullable=True)
    tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    events: Mapped[list] = mapped_column(JSON, default=list)                  # node-by-node progress (replayable)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class Outcome(Base):
    __tablename__ = "outcomes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    proposal_id: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(20))
    category: Mapped[str | None] = mapped_column(String(40), nullable=True)
    connects_spent: Mapped[int] = mapped_column(Integer, default=0)
    at: Mapped[dt.datetime] = mapped_column(DateTime, default=now)


class Rejection(Base):
    __tablename__ = "rejections"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    thread_id: Mapped[str] = mapped_column(String(128))
    reason: Mapped[str] = mapped_column(Text)
    at: Mapped[dt.datetime] = mapped_column(DateTime, default=now)


_engine = None
_Session: sessionmaker | None = None


def engine():
    global _engine, _Session
    if _engine is None:
        url = get_settings().database_url.replace("postgres://", "postgresql+psycopg://", 1)
        if url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+psycopg://", 1)
        kw: dict[str, Any] = {"pool_pre_ping": True}
        if url.startswith("sqlite"):
            kw["connect_args"] = {"check_same_thread": False}
        _engine = create_engine(url, **kw)
        _Session = sessionmaker(_engine, expire_on_commit=False)
        Base.metadata.create_all(_engine)
    return _engine


def session() -> Session:
    engine()
    return _Session()


def reset_engine() -> None:
    global _engine, _Session
    _engine, _Session = None, None


def jobs_for(s: Session, user_id: str):
    return select(JobRecord).where(JobRecord.user_id == user_id)


def dumps(o: Any) -> str:
    return json.dumps(o, default=str)
