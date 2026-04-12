from __future__ import annotations

import json
import logging
import threading
import webbrowser
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

logger = logging.getLogger(__name__)

_MISSION_CONTROL_HTML = Path(__file__).parent / "mission_control.html"
_MAX_EVENTS_PER_REQUEST = 5000


@dataclass
class Response:
    status: int
    content_type: str
    body: bytes


def _json_response(status: int, payload: dict[str, Any]) -> Response:
    return Response(
        status=status,
        content_type="application/json",
        body=json.dumps(payload).encode("utf-8"),
    )


def _parse_after_cursor(qs: dict[str, list[str]]) -> int | None:
    raw_after = qs.get("after", ["0"])[0]
    try:
        after = int(raw_after)
    except ValueError:
        return None
    return max(after, 0)


def route_request(
    path: str,
    query: str,
    *,
    watcher: Any,
    plan_data: dict[str, Any],
    trace_path: Path,
    project_path: Path,
) -> Response:
    parsed_path = urlparse(f"http://localhost{path}?{query}" if query else f"http://localhost{path}")
    url_path = parsed_path.path
    qs = parse_qs(parsed_path.query)

    if url_path in ("/", ""):
        return _build_html_response()
    if url_path == "/api/watch/state":
        return _build_state_response(watcher)
    if url_path == "/api/watch/plan":
        return _build_plan_response(plan_data)
    if url_path == "/api/events":
        after = _parse_after_cursor(qs)
        if after is None:
            return _json_response(400, {"error": "Invalid 'after' cursor"})
        return _build_events_response(trace_path, after, project_path)
    return Response(status=404, content_type="text/plain", body=b"Not Found")


def _build_html_response() -> Response:
    try:
        content = _MISSION_CONTROL_HTML.read_bytes()
    except FileNotFoundError:
        return Response(status=500, content_type="text/plain", body=b"mission_control.html not found")
    return Response(status=200, content_type="text/html; charset=utf-8", body=content)


def _build_state_response(watcher: Any) -> Response:
    state = watcher.poll()
    raw = json.dumps(state.to_dict()).encode("utf-8")
    return Response(status=200, content_type="application/json", body=raw)


def _build_plan_response(plan_data: dict[str, Any]) -> Response:
    raw = json.dumps(plan_data).encode("utf-8")
    return Response(status=200, content_type="application/json", body=raw)


def _build_events_response(trace_path: Path, after: int, project_path: Path) -> Response:
    events, total = _read_trace_events(trace_path, after, allowed_dir=project_path)

    total_tasks = 0
    for evt in events:
        if evt.get("event_type") == "task_end":
            total_tasks = max(total_tasks, _task_index(evt))
        if evt.get("event_type") == "workflow_end":
            total_tasks = evt.get("data", {}).get("total_tasks", total_tasks)

    raw = json.dumps({"events": events, "cursor": total, "total_tasks": total_tasks}).encode(
        "utf-8"
    )
    return Response(status=200, content_type="application/json", body=raw)


class WatchHandler(BaseHTTPRequestHandler):
    project_path: Path
    watcher: Any
    plan_data: dict[str, Any]
    trace_path: Path

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        resp = route_request(
            parsed.path,
            parsed.query,
            watcher=self.watcher,
            plan_data=self.plan_data,
            trace_path=self.trace_path,
            project_path=self.project_path,
        )
        self.send_response(resp.status)
        self.send_header("Content-Type", resp.content_type)
        self.send_header("Content-Length", str(len(resp.body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(resp.body)

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        """Suppress default stderr logging from BaseHTTPRequestHandler."""


def _read_trace_events(
    trace_path: Path, after: int, *, allowed_dir: Path | None = None
) -> tuple[list[dict[str, Any]], int]:
    """Read JSONL trace events from *trace_path*, skipping the first *after* lines.

    Returns ``(events, total_line_count)``.  Malformed JSON lines are silently
    skipped and I/O errors are logged but do not propagate.

    If *allowed_dir* is given, *trace_path* must resolve to a location inside
    that directory; otherwise a ``ValueError`` is raised (path-traversal guard).
    """
    resolved = trace_path.resolve()
    if allowed_dir is not None:
        allowed_resolved = allowed_dir.resolve()
        if resolved != allowed_resolved and not resolved.is_relative_to(allowed_resolved):
            raise ValueError(f"Trace path {trace_path} escapes allowed directory {allowed_dir}")

    events: list[dict[str, Any]] = []
    total = 0
    if not resolved.exists():
        return events, total

    with open(resolved, encoding="utf-8") as f:
        for i, raw_line in enumerate(f):
            total = i + 1
            if i < after:
                continue
            if len(events) >= _MAX_EVENTS_PER_REQUEST:
                break
            stripped = raw_line.strip()
            if stripped:
                evt = _parse_json_line(stripped)
                if evt is not None:
                    events.append(evt)

    return events, total


def _parse_json_line(line: str) -> dict[str, Any] | None:
    """Return parsed JSON dict or *None* for malformed lines."""
    try:
        return json.loads(line)  # type: ignore[no-any-return]
    except json.JSONDecodeError as exc:
        logger.debug("Skipping malformed trace line: %s", exc)
        return None


def _task_index(evt: dict[str, Any]) -> int:
    task_id = evt.get("data", {}).get("task_id", "")
    parts = str(task_id).split(".")
    if len(parts) < 2:
        return 0
    try:
        return int(parts[-1])
    except ValueError:
        logger.debug("Non-numeric task index in task_id %r", task_id)
        return 0


def _make_handler(
    project_path: Path,
    watcher: Any,
    plan_data: dict[str, Any],
    trace_path: Path,
) -> type[WatchHandler]:
    class BoundHandler(WatchHandler):
        pass

    BoundHandler.project_path = project_path
    BoundHandler.watcher = watcher
    BoundHandler.plan_data = plan_data
    BoundHandler.trace_path = trace_path
    return BoundHandler


def create_watch_server(
    project_path: Path,
    watcher: Any,
    plan_data: dict[str, Any],
    trace_path: Path,
    port: int = 0,
) -> HTTPServer:
    handler_cls = _make_handler(project_path, watcher, plan_data, trace_path)
    return HTTPServer(("127.0.0.1", port), handler_cls)


def start_watch_server(
    project_path: Path,
    watcher: Any,
    plan_data: dict[str, Any],
    trace_path: Path,
    port: int = 0,
    open_browser: bool = True,
) -> HTTPServer:
    server = create_watch_server(project_path, watcher, plan_data, trace_path, port)
    actual_port = server.server_address[1]

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    url = f"http://127.0.0.1:{actual_port}"
    logger.info("Watch server running at %s", url)

    if open_browser:
        webbrowser.open(url)

    return server
