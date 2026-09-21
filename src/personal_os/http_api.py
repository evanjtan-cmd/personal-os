"""Loopback-only HTTP transport for the browser work loop."""

from __future__ import annotations

import argparse
import json
from importlib.resources import files
from collections.abc import Callable, Mapping
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from personal_os.bridge import PROTOCOL_VERSION, _response, _utc_now, process_request
from personal_os.runtime import PersonalOSRuntime, build_runtime

DEFAULT_PORT = 8765
MAX_REQUEST_BYTES = 65_536
ACTIVATE_PATH = "/v1/activate"
POST_OPERATIONS = {
    ACTIVATE_PATH: ("activate", {"timezone", "time_cap_minutes"}),
    "/v1/start": (
        "start",
        {"task_id", "planned_minutes", "timezone", "available_minutes", "selected_action", "start_reason"},
    ),
    "/v1/feedback": ("feedback", {"outcome", "result_note"}),
}
STATIC_FILES = {
    "/": ("work.html", "text/html; charset=utf-8"),
    "/work.css": ("work.css", "text/css; charset=utf-8"),
    "/work.js": ("work.js", "text/javascript; charset=utf-8"),
}


def _error(
    status: HTTPStatus, message: str, operation: str | None = None
) -> tuple[HTTPStatus, dict[str, object]]:
    return status, _response(
        operation=operation,
        code="INVALID_REQUEST" if status is HTTPStatus.BAD_REQUEST else status.name,
        message=message,
    )


def create_server(
    port: int = DEFAULT_PORT,
    *,
    runtime_factory: Callable[[], PersonalOSRuntime] = build_runtime,
    clock: Callable[[], datetime] = _utc_now,
    environ: Mapping[str, str] | None = None,
) -> ThreadingHTTPServer:
    """Construct a server bound only to the IPv4 loopback address."""

    class Handler(BaseHTTPRequestHandler):
        def _origin(self) -> str:
            port = self.server.server_port
            return f"http://127.0.0.1{':' + str(port) if port != 80 else ''}"

        def _valid_host(self) -> bool:
            return self.headers.get_all("Host", []) == [self._origin().removeprefix("http://")]

        def _headers(self, content_type: str, length: int) -> None:
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(length))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; script-src 'self'; style-src 'self'; "
                "connect-src 'self'; img-src 'self'; object-src 'none'; base-uri 'none'; "
                "frame-ancestors 'none'; form-action 'self'",
            )
            self.send_header("Cache-Control", "no-store")

        def _write(self, status: HTTPStatus, body: dict[str, object]) -> None:
            encoded = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode(
                "utf-8"
            )
            self.send_response(status)
            self._headers("application/json; charset=utf-8", len(encoded))
            self.end_headers()
            self.wfile.write(encoded)

        def do_POST(self) -> None:
            if not self._valid_host():
                self._write(*_error(HTTPStatus.BAD_REQUEST, "invalid Host header"))
                return
            route = POST_OPERATIONS.get(self.path)
            if route is None:
                self._write(*_error(HTTPStatus.NOT_FOUND, "unknown endpoint"))
                return
            operation, allowed_fields = route
            origins = self.headers.get_all("Origin", [])
            if origins and origins != [self._origin()]:
                self._write(*_error(HTTPStatus.FORBIDDEN, "cross-origin request rejected", operation))
                return
            fetch_sites = self.headers.get_all("Sec-Fetch-Site", [])
            if fetch_sites and fetch_sites not in (["same-origin"], ["none"]):
                self._write(*_error(HTTPStatus.FORBIDDEN, "cross-origin request rejected", operation))
                return
            if self.headers.get_content_type() != "application/json":
                self._write(*_error(
                    HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
                    "Content-Type must be application/json",
                    operation,
                ))
                return
            try:
                length = int(self.headers.get("Content-Length", ""))
            except ValueError:
                length = -1
            if length < 1 or length > MAX_REQUEST_BYTES:
                self._write(*_error(
                    HTTPStatus.BAD_REQUEST,
                    "Content-Length must be between 1 and 65536",
                    operation,
                ))
                return
            try:
                payload: Any = json.loads(self.rfile.read(length))
            except (UnicodeDecodeError, json.JSONDecodeError):
                self._write(*_error(
                    HTTPStatus.BAD_REQUEST,
                    "body must contain one valid JSON value",
                    operation,
                ))
                return
            if isinstance(payload, dict):
                unknown = payload.keys() - allowed_fields
                if unknown:
                    self._write(*_error(
                        HTTPStatus.BAD_REQUEST,
                        f"unknown field: {sorted(unknown)[0]}",
                        operation,
                    ))
                    return
                payload = {**payload, "version": PROTOCOL_VERSION, "operation": operation}
            status, response = process_request(
                payload,
                runtime_factory=runtime_factory,
                clock=clock,
                environ=environ,
                expected_operation=operation,
            )
            http_status = (
                HTTPStatus.OK if status == 0
                else HTTPStatus.BAD_REQUEST if status == 2
                else HTTPStatus.INTERNAL_SERVER_ERROR
            )
            self._write(http_status, response)

        def do_GET(self) -> None:
            if not self._valid_host():
                self._write(*_error(HTTPStatus.BAD_REQUEST, "invalid Host header"))
                return
            if self.path in POST_OPERATIONS:
                self._method_not_allowed()
                return
            resource = STATIC_FILES.get(self.path)
            if resource is None:
                self._write(*_error(HTTPStatus.NOT_FOUND, "unknown endpoint"))
                return
            name, content_type = resource
            body = files("personal_os").joinpath("static", name).read_bytes()
            self.send_response(HTTPStatus.OK)
            self._headers(content_type, len(body))
            self.end_headers()
            self.wfile.write(body)

        def _method_not_allowed(self) -> None:
            if not self._valid_host():
                self._write(*_error(HTTPStatus.BAD_REQUEST, "invalid Host header"))
                return
            self._write(*_error(HTTPStatus.METHOD_NOT_ALLOWED, "method not allowed"))

        do_PUT = _method_not_allowed
        do_PATCH = _method_not_allowed
        do_DELETE = _method_not_allowed
        do_OPTIONS = _method_not_allowed

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def _port(value: str) -> int:
    try:
        port = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("port must be an integer from 1 to 65535") from exc
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError("port must be an integer from 1 to 65535")
    return port


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Serve the local Personal OS Work interface"
    )
    parser.add_argument("--port", type=_port, default=DEFAULT_PORT)
    args = parser.parse_args(argv)
    with create_server(args.port) as server:
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
