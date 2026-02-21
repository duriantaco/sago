import json
from http.client import HTTPConnection
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from sago.web.server import start_watch_server


def _make_mock_watcher() -> MagicMock:
    """Create a mock watcher that returns a minimal state."""
    watcher = MagicMock()
    state = MagicMock()
    state.to_dict.return_value = {
        "tasks": [],
        "progress": {"done": 0, "failed": 0, "total": 0, "pct": 0},
        "phases": [],
        "recent_files": [],
        "md_files": [],
        "last_updated": "2025-01-01T00:00:00+00:00",
    }
    watcher.poll.return_value = state
    return watcher


@pytest.fixture()
def trace_file(tmp_path: Path) -> Path:
    """Create a trace file with sample events."""
    path = tmp_path / "trace.jsonl"
    events = [
        {
            "event_type": "workflow_start",
            "timestamp": "2025-01-01T00:00:00+00:00",
            "trace_id": "abc123",
            "span_id": "s1",
            "agent": "Orchestrator",
            "data": {"project_path": "/tmp/test"},
            "parent_span_id": None,
            "duration_ms": None,
        },
        {
            "event_type": "file_read",
            "timestamp": "2025-01-01T00:00:01+00:00",
            "trace_id": "abc123",
            "span_id": "s2",
            "agent": "PlannerAgent",
            "data": {"path": "PROJECT.md", "size_bytes": 512},
            "parent_span_id": None,
            "duration_ms": None,
        },
        {
            "event_type": "llm_call",
            "timestamp": "2025-01-01T00:00:05+00:00",
            "trace_id": "abc123",
            "span_id": "s3",
            "agent": "PlannerAgent",
            "data": {"model": "gpt-4o", "total_tokens": 1500, "duration_s": 3.2},
            "parent_span_id": None,
            "duration_ms": 3200.0,
        },
    ]
    with open(path, "w", encoding="utf-8") as f:
        for evt in events:
            f.write(json.dumps(evt) + "\n")
    return path


@pytest.fixture()
def server(trace_file: Path, tmp_path: Path):
    watcher = _make_mock_watcher()
    plan_data = {"project_name": "test", "phases": [], "dependencies": []}
    srv = start_watch_server(
        project_path=tmp_path,
        watcher=watcher,
        plan_data=plan_data,
        trace_path=trace_file,
        port=0,
        open_browser=False,
    )
    port = srv.server_address[1]
    conn = HTTPConnection("127.0.0.1", port, timeout=5)
    yield conn, srv
    srv.shutdown()
    conn.close()


def test_server_serves_html(server: tuple) -> None:
    conn, _srv = server
    conn.request("GET", "/")
    resp = conn.getresponse()
    assert resp.status == 200
    body = resp.read().decode()
    assert "Sago Watch" in body
    assert "text/html" in resp.getheader("Content-Type", "")


def test_server_returns_events(server: tuple) -> None:
    conn, _srv = server
    conn.request("GET", "/api/events?after=0")
    resp = conn.getresponse()
    assert resp.status == 200
    data = json.loads(resp.read())
    assert "events" in data
    assert "cursor" in data
    assert len(data["events"]) == 3
    assert data["cursor"] == 3
    assert data["events"][0]["event_type"] == "workflow_start"


def test_server_after_parameter(server: tuple) -> None:
    conn, _srv = server

    conn.request("GET", "/api/events?after=2")
    resp = conn.getresponse()
    assert resp.status == 200
    data = json.loads(resp.read())
    assert len(data["events"]) == 1
    assert data["events"][0]["event_type"] == "llm_call"
    assert data["cursor"] == 3

    conn.request("GET", "/api/events?after=3")
    resp = conn.getresponse()
    data = json.loads(resp.read())
    assert len(data["events"]) == 0
    assert data["cursor"] == 3


def test_server_empty_trace(tmp_path: Path) -> None:
    empty_path = tmp_path / "empty.jsonl"
    watcher = _make_mock_watcher()
    plan_data = {"project_name": "test", "phases": [], "dependencies": []}
    srv = start_watch_server(
        project_path=tmp_path,
        watcher=watcher,
        plan_data=plan_data,
        trace_path=empty_path,
        port=0,
        open_browser=False,
    )
    port = srv.server_address[1]
    conn = HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        conn.request("GET", "/api/events?after=0")
        resp = conn.getresponse()
        assert resp.status == 200
        data = json.loads(resp.read())
        assert data["events"] == []
    finally:
        srv.shutdown()
        conn.close()


def test_server_watch_state(server: tuple) -> None:
    conn, _srv = server
    conn.request("GET", "/api/watch/state")
    resp = conn.getresponse()
    assert resp.status == 200
    data = json.loads(resp.read())
    assert "tasks" in data
    assert "progress" in data


def test_server_watch_plan(server: tuple) -> None:
    conn, _srv = server
    conn.request("GET", "/api/watch/plan")
    resp = conn.getresponse()
    assert resp.status == 200
    data = json.loads(resp.read())
    assert data["project_name"] == "test"
