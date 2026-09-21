"""Loopback-only HTTP transport for work activation."""

from __future__ import annotations

import argparse
import json
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


def _error(status: HTTPStatus, message: str) -> tuple[HTTPStatus, dict[str, object]]:
    return status, _response(
        operation="activate" if status is not HTTPStatus.NOT_FOUND else None,
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
        def _write(self, status: HTTPStatus, body: dict[str, object]) -> None:
            encoded = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode(
                "utf-8"
            )
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def do_POST(self) -> None:
            if self.path != ACTIVATE_PATH:
                self._write(*_error(HTTPStatus.NOT_FOUND, "unknown endpoint"))
                return
            if self.headers.get_content_type() != "application/json":
                self._write(*_error(
                    HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
                    "Content-Type must be application/json",
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
                ))
                return
            try:
                payload: Any = json.loads(self.rfile.read(length))
            except (UnicodeDecodeError, json.JSONDecodeError):
                self._write(*_error(
                    HTTPStatus.BAD_REQUEST,
                    "body must contain one valid JSON value",
                ))
                return
            if isinstance(payload, dict):
                payload = {"version": PROTOCOL_VERSION, "operation": "activate", **payload}
            status, response = process_request(
                payload,
                runtime_factory=runtime_factory,
                clock=clock,
                environ=environ,
                expected_operation="activate",
            )
            http_status = (
                HTTPStatus.OK if status == 0
                else HTTPStatus.BAD_REQUEST if status == 2
                else HTTPStatus.INTERNAL_SERVER_ERROR
            )
            self._write(http_status, response)

        def do_GET(self) -> None:
            self._write(*_error(HTTPStatus.METHOD_NOT_ALLOWED, "method not allowed"))

        do_PUT = do_GET
        do_PATCH = do_GET
        do_DELETE = do_GET
        do_OPTIONS = do_GET

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
        description="Serve the local Personal OS activation API"
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
