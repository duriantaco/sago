import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from sago.web.server import route_request


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
def ctx(trace_file: Path, tmp_path: Path) -> dict:
    """Shared keyword args for route_request()."""
    return {
        "watcher": _make_mock_watcher(),
        "plan_data": {"project_name": "test", "phases": [], "dependencies": []},
        "trace_path": trace_file,
        "project_path": tmp_path,
    }


def test_serves_html(ctx: dict) -> None:
    resp = route_request("/", "", **ctx)
    assert resp.status == 200
    assert "text/html" in resp.content_type
    assert b"Sago Watch" in resp.body


def test_returns_events(ctx: dict) -> None:
    resp = route_request("/api/events", "after=0", **ctx)
    assert resp.status == 200
    data = json.loads(resp.body)
    assert "events" in data
    assert "cursor" in data
    assert len(data["events"]) == 3
    assert data["cursor"] == 3
    assert data["events"][0]["event_type"] == "workflow_start"


def test_after_parameter(ctx: dict) -> None:
    resp = route_request("/api/events", "after=2", **ctx)
    assert resp.status == 200
    data = json.loads(resp.body)
    assert len(data["events"]) == 1
    assert data["events"][0]["event_type"] == "llm_call"
    assert data["cursor"] == 3

    resp2 = route_request("/api/events", "after=3", **ctx)
    data2 = json.loads(resp2.body)
    assert len(data2["events"]) == 0
    assert data2["cursor"] == 3


def test_invalid_after_parameter_returns_400(ctx: dict) -> None:
    resp = route_request("/api/events", "after=abc", **ctx)
    assert resp.status == 400
    data = json.loads(resp.body)
    assert "error" in data


def test_empty_trace(tmp_path: Path) -> None:
    ctx = {
        "watcher": _make_mock_watcher(),
        "plan_data": {"project_name": "test", "phases": [], "dependencies": []},
        "trace_path": tmp_path / "empty.jsonl",
        "project_path": tmp_path,
    }
    resp = route_request("/api/events", "after=0", **ctx)
    assert resp.status == 200
    data = json.loads(resp.body)
    assert data["events"] == []


def test_watch_state(ctx: dict) -> None:
    resp = route_request("/api/watch/state", "", **ctx)
    assert resp.status == 200
    data = json.loads(resp.body)
    assert "tasks" in data
    assert "progress" in data


def test_watch_plan(ctx: dict) -> None:
    resp = route_request("/api/watch/plan", "", **ctx)
    assert resp.status == 200
    data = json.loads(resp.body)
    assert data["project_name"] == "test"


def test_not_found(ctx: dict) -> None:
    resp = route_request("/nonexistent", "", **ctx)
    assert resp.status == 404
