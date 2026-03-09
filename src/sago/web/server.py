from __future__ import annotations

import json
import logging
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

logger = logging.getLogger(__name__)

_MISSION_CONTROL_HTML = Path(__file__).parent / "mission_control.html"
_MAX_EVENTS_PER_REQUEST = 5000


class WatchHandler(BaseHTTPRequestHandler):
    project_path: Path
    watcher: Any
    plan_data: dict[str, Any]
    trace_path: Path

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)

        if parsed.path in ("/", ""):
            self._serve_html()
        elif parsed.path == "/api/watch/state":
            self._serve_state()
        elif parsed.path == "/api/watch/plan":
            self._serve_plan()
        elif parsed.path == "/api/events":
            qs = parse_qs(parsed.query)
            after = int(qs.get("after", ["0"])[0])
            self._serve_events(after)
        else:
            self.send_error(404)

    def _serve_html(self) -> None:
        try:
            content = _MISSION_CONTROL_HTML.read_bytes()
        except FileNotFoundError:
            self.send_error(500, "mission_control.html not found")
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self._cors_headers()
        self.end_headers()
        self.wfile.write(content)

    def _serve_state(self) -> None:
        state = self.watcher.poll()
        body = json.dumps(state.to_dict())
        raw = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self._cors_headers()
        self.end_headers()
        self.wfile.write(raw)

    def _serve_plan(self) -> None:
        body = json.dumps(self.plan_data)
        raw = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self._cors_headers()
        self.end_headers()
        self.wfile.write(raw)

    def _serve_events(self, after: int) -> None:
        events, total = _read_trace_events(
            self.trace_path, after, allowed_dir=self.project_path
        )

        total_tasks = 0
        for evt in events:
            if evt.get("event_type") == "task_end":
                total_tasks = max(total_tasks, _task_index(evt))
            if evt.get("event_type") == "workflow_end":
                total_tasks = evt.get("data", {}).get("total_tasks", total_tasks)

        body = json.dumps({"events": events, "cursor": total, "total_tasks": total_tasks})
        raw = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self._cors_headers()
        self.end_headers()
        self.wfile.write(raw)

    def _cors_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")

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
        is_inside = str(resolved).startswith(str(allowed_resolved) + "/")
        if not is_inside and resolved != allowed_resolved:
            raise ValueError(
                f"Trace path {trace_path} escapes allowed directory {allowed_dir}"
            )

    events: list[dict[str, Any]] = []
    total = 0
    if not resolved.exists():
        return events, total

    with open(resolved, encoding="utf-8") as f:  # noqa: SKY-D215 — path validated above
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


def start_watch_server(
    project_path: Path,
    watcher: Any,
    plan_data: dict[str, Any],
    trace_path: Path,
    port: int = 0,
    open_browser: bool = True,
) -> HTTPServer:
    handler_cls = _make_handler(project_path, watcher, plan_data, trace_path)
    server = HTTPServer(("127.0.0.1", port), handler_cls)
    actual_port = server.server_address[1]

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    url = f"http://127.0.0.1:{actual_port}"
    logger.info("Watch server running at %s", url)

    if open_browser:
        webbrowser.open(url)

    return server
