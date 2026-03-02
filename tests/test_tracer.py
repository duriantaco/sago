import json
import threading
from pathlib import Path

import pytest

from sago.utils.tracer import Tracer


@pytest.fixture()
def tmp_trace(tmp_path: Path) -> Path:
    return tmp_path / "trace.jsonl"


@pytest.fixture()
def fresh_tracer() -> Tracer:
    return Tracer()


def test_tracer_disabled_by_default(fresh_tracer: Tracer) -> None:
    assert not fresh_tracer.enabled
    result = fresh_tracer.emit("test", "Agent", {"key": "value"})
    assert result is None


def test_tracer_configure_and_emit(fresh_tracer: Tracer, tmp_trace: Path) -> None:
    fresh_tracer.configure(tmp_trace, model="gpt-4o")
    assert fresh_tracer.enabled
    assert len(fresh_tracer.trace_id) == 16

    event = fresh_tracer.emit("file_read", "PlannerAgent", {"path": "README.md", "size_bytes": 42})
    fresh_tracer.close()

    assert event is not None
    assert event.event_type == "file_read"
    assert event.agent == "PlannerAgent"
    assert event.data["path"] == "README.md"

    lines = tmp_trace.read_text().strip().splitlines()
    assert len(lines) == 1
    parsed = json.loads(lines[0])
    assert parsed["event_type"] == "file_read"
    assert parsed["trace_id"] == fresh_tracer.trace_id


def test_tracer_span_tracks_duration(fresh_tracer: Tracer, tmp_trace: Path) -> None:
    fresh_tracer.configure(tmp_trace)

    with fresh_tracer.span("llm_call", "ExecutorAgent", {"model": "gpt-4o"}):
        pass  # instant span

    fresh_tracer.close()

    lines = tmp_trace.read_text().strip().splitlines()
    assert len(lines) == 2  # start + end

    start = json.loads(lines[0])
    end = json.loads(lines[1])
    assert start["event_type"] == "llm_call_start"
    assert end["event_type"] == "llm_call_end"
    assert end["duration_ms"] is not None
    assert end["duration_ms"] >= 0
    assert end["data"]["duration_ms"] >= 0


def test_tracer_parent_span_nesting(fresh_tracer: Tracer, tmp_trace: Path) -> None:
    fresh_tracer.configure(tmp_trace)

    with fresh_tracer.span("outer", "Agent") as outer:
        inner_event = fresh_tracer.emit("inner_event", "Agent", {"x": 1})

    fresh_tracer.close()

    assert inner_event is not None
    assert inner_event.parent_span_id == outer.span_id

    lines = tmp_trace.read_text().strip().splitlines()
    assert len(lines) == 3  # outer_start, inner_event, outer_end


def test_tracer_close_and_reset(fresh_tracer: Tracer, tmp_trace: Path) -> None:
    fresh_tracer.configure(tmp_trace, model="test")
    assert fresh_tracer.enabled
    fresh_tracer.close()
    assert not fresh_tracer.enabled

    result = fresh_tracer.emit("test", "Agent")
    assert result is None

    fresh_tracer.reset()
    assert fresh_tracer.trace_id == ""


def test_tracer_thread_safety(fresh_tracer: Tracer, tmp_trace: Path) -> None:
    fresh_tracer.configure(tmp_trace)
    n_threads = 10
    n_events = 50
    errors: list[Exception] = []

    def emit_events() -> None:
        try:
            for i in range(n_events):
                fresh_tracer.emit("test", "Thread", {"i": i})
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=emit_events) for _ in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    fresh_tracer.close()

    assert not errors
    lines = tmp_trace.read_text().strip().splitlines()
    assert len(lines) == n_threads * n_events

    for line in lines:
        parsed = json.loads(line)
        assert parsed["event_type"] == "test"


def test_tracer_span_disabled(fresh_tracer: Tracer) -> None:
    with fresh_tracer.span("test", "Agent") as state:
        assert state.span_id == ""
