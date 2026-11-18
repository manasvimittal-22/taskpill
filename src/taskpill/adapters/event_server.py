"""Local HTTP server the hook helper and the VS Code extension talk to.

Endpoints (all need the ``X-TaskPill-Token`` header):
    POST /event    one hook event (JSON)          → 204, or 400/401/403/411/413
    POST /click    {"session_id": "…"}            → 204: same as clicking that pill
    GET  /health   {"app": "taskpill", ...}       → 200
    GET  /stream   Server-Sent Events: the latest snapshot, then every change

Security:
* Bound to 127.0.0.1 only, so nothing outside this computer can connect.
* A random token (from runtime.json) is required on every request, compared
  in constant time.
* Requests with an ``Origin`` header or a foreign ``Host`` are refused. That
  blocks web pages (and DNS-rebinding tricks) from talking to the app.
* Bodies are capped at 64 KB.

Threading: requests run on server threads. ``sink`` is called on those
threads, so the app must hand events to its main thread (the Qt app does it
with a signal). ``publish`` may be called from any thread.
"""

from __future__ import annotations

import hmac
import json
import threading
from collections.abc import Callable
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from taskpill import __version__
from taskpill.domain.events import HookEvent, InvalidEventError

MAX_BODY = 64 * 1024
TOKEN_HEADER = "X-TaskPill-Token"
KEEPALIVE_SECONDS = 15.0

EventSink = Callable[[HookEvent], None]


class SnapshotHub:
    """Holds the latest snapshot and wakes every /stream client when it changes."""

    def __init__(self) -> None:
        self._cond = threading.Condition()
        self._version = 0
        self._data = "{}"
        self._closed = False

    def publish(self, snapshot: Any) -> None:
        data = json.dumps(snapshot, separators=(",", ":"))
        with self._cond:
            self._data = data
            self._version += 1
            self._cond.notify_all()

    def wait(self, seen: int, timeout: float) -> tuple[int, str] | None:
        """Block until a version newer than ``seen``. None on timeout or close."""
        with self._cond:
            self._cond.wait_for(lambda: self._closed or self._version != seen, timeout)
            if self._closed or self._version == seen:
                return None
            return self._version, self._data

    def current(self) -> tuple[int, str]:
        with self._cond:
            return self._version, self._data

    @property
    def closed(self) -> bool:
        with self._cond:
            return self._closed

    def close(self) -> None:
        with self._cond:
            self._closed = True
            self._cond.notify_all()


class EventServer:
    def __init__(
        self,
        sink: EventSink,
        token: str,
        host: str = "127.0.0.1",
        port: int = 0,
        keepalive_seconds: float = KEEPALIVE_SECONDS,
        on_click: Callable[[str], None] | None = None,
    ) -> None:
        if len(token) < 16:
            raise ValueError("token is too short")
        self._sink = sink
        self._on_click = on_click
        self._token = token
        self._host = host
        self._requested_port = port
        self._keepalive = keepalive_seconds
        self.hub = SnapshotHub()
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def token(self) -> str:
        return self._token

    @property
    def port(self) -> int:
        if self._httpd is None:
            raise RuntimeError("server is not running")
        return self._httpd.server_address[1]

    def start(self) -> int:
        handler = _make_handler(self)
        self._httpd = ThreadingHTTPServer((self._host, self._requested_port), handler)
        self._httpd.daemon_threads = True
        httpd = self._httpd
        self._thread = threading.Thread(
            target=lambda: httpd.serve_forever(poll_interval=0.05),
            name="taskpill-server",
            daemon=True,
        )
        self._thread.start()
        return self.port

    def stop(self) -> None:
        self.hub.close()
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None

    def publish(self, snapshot: Any) -> None:
        self.hub.publish(snapshot)

    # used by the handler
    def _token_ok(self, given: str | None) -> bool:
        return given is not None and hmac.compare_digest(given.encode(), self._token.encode())

    def _host_ok(self, host_header: str | None) -> bool:
        allowed = {f"127.0.0.1:{self.port}", f"localhost:{self.port}"}
        return host_header in allowed


def _make_handler(server: EventServer) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "TaskPill"
        sys_version = ""
        protocol_version = "HTTP/1.1"

        # ---- routing ----------------------------------------------------
        def do_POST(self) -> None:  # noqa: N802 (http.server naming)
            if not self._guard():
                return
            if self.path == "/event":
                self._handle_event()
            elif self.path == "/click" and server._on_click is not None:
                self._handle_click()
            else:
                self._reply(HTTPStatus.NOT_FOUND)

        def do_GET(self) -> None:  # noqa: N802
            if not self._guard():
                return
            if self.path == "/health":
                self._reply_json({"app": "taskpill", "version": __version__})
            elif self.path == "/stream":
                self._handle_stream()
            else:
                self._reply(HTTPStatus.NOT_FOUND)

        # ---- checks -----------------------------------------------------
        def _guard(self) -> bool:
            if self.headers.get("Origin") is not None or not server._host_ok(
                self.headers.get("Host")
            ):
                self._reply(HTTPStatus.FORBIDDEN)
                return False
            if not server._token_ok(self.headers.get(TOKEN_HEADER)):
                self._reply(HTTPStatus.UNAUTHORIZED)
                return False
            return True

        # ---- handlers ---------------------------------------------------
        def _read_body(self) -> bytes | None:
            """The request body, or None after replying with an error."""
            length_header = self.headers.get("Content-Length")
            if length_header is None:
                self._reply(HTTPStatus.LENGTH_REQUIRED)
                return None
            try:
                length = int(length_header)
            except ValueError:
                self._reply(HTTPStatus.BAD_REQUEST)
                return None
            if length < 0 or length > MAX_BODY:
                self._reply(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, close=True)
                return None
            return self.rfile.read(length)

        def _handle_click(self) -> None:
            body = self._read_body()
            if body is None:
                return
            try:
                data = json.loads(body)
            except ValueError:
                data = None
            session_id = data.get("session_id") if isinstance(data, dict) else None
            if not isinstance(session_id, str) or not 0 < len(session_id) <= 200:
                self._reply(HTTPStatus.BAD_REQUEST)
                return
            try:
                server._on_click(session_id)
            except Exception:
                self._reply(HTTPStatus.INTERNAL_SERVER_ERROR)
                return
            self._reply(HTTPStatus.NO_CONTENT)

        def _handle_event(self) -> None:
            body = self._read_body()
            if body is None:
                return
            try:
                event = HookEvent.from_payload(json.loads(body))
            except (ValueError, InvalidEventError):  # JSONDecodeError is a ValueError
                self._reply(HTTPStatus.BAD_REQUEST)
                return
            try:
                server._sink(event)
            except Exception:  # a bug in the app must not take the server down
                self._reply(HTTPStatus.INTERNAL_SERVER_ERROR)
                return
            self._reply(HTTPStatus.NO_CONTENT)

        def _handle_stream(self) -> None:
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "close")
            self.end_headers()
            self.close_connection = True
            hub = server.hub
            seen, data = hub.current()
            try:
                self._send_event(data)
                while not hub.closed:
                    update = hub.wait(seen, server._keepalive)
                    if update is None:
                        self.wfile.write(b": keepalive\n\n")
                    else:
                        seen, data = update
                        self._send_event(data)
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
                return  # the client went away

        # ---- helpers ----------------------------------------------------
        def _send_event(self, data: str) -> None:
            self.wfile.write(f"data: {data}\n\n".encode())
            self.wfile.flush()

        def _reply(self, status: HTTPStatus, close: bool = False) -> None:
            self.send_response(status)
            self.send_header("Content-Length", "0")
            if close:
                self.send_header("Connection", "close")
                self.close_connection = True
            self.end_headers()

        def _reply_json(self, payload: Any) -> None:
            body = json.dumps(payload).encode()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
            return  # stay quiet; never log prompts or tokens

    return Handler
