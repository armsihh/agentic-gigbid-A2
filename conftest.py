"""Shared fixtures: an in-process GigSim and helpers to talk to MCP servers over in-memory sessions."""
from __future__ import annotations

import os

os.environ.setdefault("GIGSIM_ERROR_RATE", "0")
os.environ.setdefault("GIGSIM_SLOW_RATE", "0")
os.environ.setdefault("GIGSIM_RPM", "100000")
os.environ.setdefault("APP_SECRET_KEY", "test-secret-not-for-prod")

import httpx
import pytest

from gigsim.app import _buckets, world
from gigsim.app import app as gigsim_app
from mcp_servers.marketplace.adapters.gigsim import GigSimAdapter


@pytest.fixture
def gigsim():
    world.reset()
    _buckets.clear()
    world.cfg["faults"].update(error_rate=0, slow_rate=0)
    world.cfg["rate_limit"]["requests_per_minute"] = 100000
    return world


@pytest.fixture
def adapter_factory(gigsim):
    def make(_user: str = "local", **kw):
        return GigSimAdapter(base_url="http://gigsim", transport=httpx.ASGITransport(app=gigsim_app),
                             backoff_base_s=0.001, **kw)
    return make


@pytest.fixture
def audit_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("AUDIT_LOG_DIR", str(tmp_path / "audit"))
    return tmp_path / "audit"
