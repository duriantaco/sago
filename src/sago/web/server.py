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
    """Unified handler serving the combined mission control + trace UI."""

    project_path: Path
    watcher: Any  # ProjectWatcher
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
        events: list[dict[str, Any]] = []
        total = 0

        try:
            if self.trace_path.exists():
                with open(self.trace_path, encoding="utf-8") as f:
                    for i, line in enumerate(f):
                        total = i + 1
                        if i < after:
                            continue
                        if len(events) >= _MAX_EVENTS_PER_REQUEST:
                            break
                        line = line.strip()
                        if line:
                            try:
                                events.append(json.loads(line))
                            except json.JSONDecodeError:
                                pass
        except Exception as exc:
            logger.warning("Error reading trace file: %s", exc)

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

    def log_message(self, format: str, *args: Any) -> None:
        """Suppress default stderr logging."""
        pass


def _task_index(evt: dict[str, Any]) -> int:
    task_id = evt.get("data", {}).get("task_id", "")
    parts = str(task_id).split(".")
    if len(parts) >= 2:
        try:
            return int(parts[-1])
        except ValueError:
            pass
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
    """Start the unified watch server in a daemon thread.

    Serves the combined mission control + trace UI on a single port.

    Args:
        project_path: Path to the project directory.
        watcher: ProjectWatcher instance.
        plan_data: Pre-parsed plan structure (phases, dependencies).
        trace_path: Path to the JSONL trace file.
        port: Port to bind (0 = OS-assigned).
        open_browser: Whether to auto-open in browser.

    Returns:
        The running HTTPServer instance (call .shutdown() to stop).
    """
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
