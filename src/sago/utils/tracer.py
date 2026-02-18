from __future__ import annotations

import json
import threading
import time
import uuid
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


@dataclass
class TraceEvent:
    event_type: str
    timestamp: str
    trace_id: str
    span_id: str
    agent: str
    data: dict[str, Any]
    parent_span_id: str | None = None
    duration_ms: float | None = None

    def to_json(self) -> str:
        return json.dumps(asdict(self), default=str)


@dataclass
class _SpanState:
    """Internal state for an active span."""

    span_id: str
    event_type: str
    agent: str
    data: dict[str, Any]
    start_ns: int


class Tracer:
    """Writes JSONL trace events. Thread-safe singleton pattern.

    Usage::

        from sago.utils.tracer import tracer

        tracer.configure(Path(".planning/trace.jsonl"))
        tracer.emit("file_read", "PlannerAgent", {"path": "PROJECT.md", "size_bytes": 1024})

        with tracer.span("llm_call", "ExecutorAgent", {"model": "gpt-4o"}):
            ...  # duration measured automatically

        tracer.close()
    """

    def __init__(self) -> None:
        self._enabled = False
        self._lock = threading.Lock()
        self._file: Any = None
        self._trace_id: str = ""
        self._model: str = ""
        self._span_stack: threading.local = threading.local()

    def configure(
        self,
        trace_path: Path,
        model: str = "",
    ) -> None:
        with self._lock:
            if self._file is not None:
                self._file.close()
            trace_path.parent.mkdir(parents=True, exist_ok=True)
            self._file = open(trace_path, "a", encoding="utf-8")  # noqa: SIM115
            self._trace_id = uuid.uuid4().hex[:16]
            self._model = model
            self._enabled = True

    def close(self) -> None:
        with self._lock:
            if self._file is not None:
                self._file.close()
                self._file = None
            self._enabled = False

    def reset(self) -> None:
        self.close()
        with self._lock:
            self._trace_id = ""
            self._model = ""

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def trace_id(self) -> str:
        return self._trace_id


    def emit(
        self,
        event_type: str,
        agent: str,
        data: dict[str, Any] | None = None,
        duration_ms: float | None = None,
    ) -> TraceEvent | None:
        
        if not self._enabled:
            return None

        parent_span_id = self._current_parent_span_id()

        event = TraceEvent(
            event_type=event_type,
            timestamp=datetime.now(UTC).isoformat(),
            trace_id=self._trace_id,
            span_id=uuid.uuid4().hex[:16],
            agent=agent,
            data=data or {},
            parent_span_id=parent_span_id,
            duration_ms=duration_ms,
        )

        with self._lock:
            if self._file is not None:
                self._file.write(event.to_json() + "\n")
                self._file.flush()

        return event

    @contextmanager
    def span(
        self,
        event_type: str,
        agent: str,
        data: dict[str, Any] | None = None,
    ) -> Generator[_SpanState, None, None]:
        """Context manager that emits paired start/end events with duration.

        Yields a ``_SpanState`` so callers can attach extra data before the
        end event is emitted.
        """
        if not self._enabled:
            state = _SpanState(
                span_id="",
                event_type=event_type,
                agent=agent,
                data=data or {},
                start_ns=time.monotonic_ns(),
            )
            yield state
            return

        span_id = uuid.uuid4().hex[:16]
        start_ns = time.monotonic_ns()

        state = _SpanState(
            span_id=span_id,
            event_type=event_type,
            agent=agent,
            data=data or {},
            start_ns=start_ns,
        )

        stack = self._get_span_stack()
        stack.append(span_id)

        self.emit(f"{event_type}_start", agent, data)

        try:
            yield state
        finally:
            duration_ms = (time.monotonic_ns() - start_ns) / 1_000_000

            if stack and stack[-1] == span_id:
                stack.pop()

            end_data = dict(state.data)
            end_data["duration_ms"] = round(duration_ms, 2)
            self.emit(f"{event_type}_end", agent, end_data, duration_ms=duration_ms)


    def _get_span_stack(self) -> list[str]:
        if not hasattr(self._span_stack, "stack"):
            self._span_stack.stack = []
        return self._span_stack.stack

    def _current_parent_span_id(self) -> str | None:
        stack = self._get_span_stack()
        return stack[-1] if stack else None


tracer = Tracer()
