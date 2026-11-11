"""Workspace MCP server through an in-memory MCP client session (A7)."""
from __future__ import annotations

import datetime as dt

import pytest
from mcp.shared.memory import create_connected_server_and_client_session as connect

from mcp_servers.workspace.server import WorkspaceStore, build_server


@pytest.fixture
def server(tmp_path, audit_dir):
    return build_server(WorkspaceStore(tmp_path / "ws"))._mcp_server


def days(n: int) -> str:
    return str(dt.date.today() + dt.timedelta(days=n))


async def test_free_slots_are_in_working_hours_and_future(server):
    async with connect(server) as s:
        r = await s.call_tool("get_free_slots", {"start_date": days(1), "end_date": days(7), "max_slots": 5})
    slots = r.structuredContent["slots"]
    assert slots
    for x in slots:
        start = dt.datetime.fromisoformat(x["start"])
        assert 9 <= start.hour < 18 and start.weekday() < 5


async def test_hold_is_idempotent_tentative_and_blocks_the_slot(server):
    async with connect(server) as s:
        slot = (await s.call_tool("get_free_slots", {"start_date": days(1), "end_date": days(7)})
                ).structuredContent["slots"][0]
        args = {"start": slot["start"], "duration_minutes": 30, "title": "Interview", "idempotency_key": "hold-000001"}
        a = await s.call_tool("create_interview_hold", args)
        b = await s.call_tool("create_interview_hold", args)
        clash = await s.call_tool("create_interview_hold", args | {"idempotency_key": "hold-000002"})
        again = (await s.call_tool("get_free_slots", {"start_date": days(1), "end_date": days(7)})).structuredContent
    assert a.structuredContent["hold"] == b.structuredContent["hold"]
    assert a.structuredContent["hold"]["status"] == "tentative"
    assert clash.isError and "[conflict]" in clash.content[0].text
    assert slot["start"] not in [x["start"] for x in again["slots"]]


async def test_email_is_only_a_draft(server):
    async with connect(server) as s:
        r = await s.call_tool("create_email_draft", {"to": "client@example.com", "subject": "Interview",
                                                     "body": "Hi", "idempotency_key": "mail-000001"})
    assert r.structuredContent["draft"]["status"] == "draft"


async def test_invalid_inputs(server):
    async with connect(server) as s:
        bad_range = await s.call_tool("get_free_slots", {"start_date": days(5), "end_date": days(1)})
        naive = await s.call_tool("create_interview_hold", {"start": "2030-01-01T10:00:00", "duration_minutes": 30,
                                                            "title": "x y z", "idempotency_key": "hold-000003"})
    assert bad_range.isError
    assert naive.isError and "timezone" in naive.content[0].text
