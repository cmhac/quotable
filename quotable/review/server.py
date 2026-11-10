"""
The review app's HTTP server (spec 013, section B): standard library only, 127.0.0.1 only.

``make_server(project_dir, port)`` returns a :class:`ReviewServer`; call ``serve_forever()`` on it
and ``server_close()`` when done. It serves ``GET /`` and ``GET /static/<name>`` (files of
``quotable/review/static/``, by name only) and dispatches ``/api/...`` requests through a route
table. To add an endpoint, write ``func(request: Request) -> JSON-able`` in its own module
(raise :class:`NotFound`, :class:`BadRequest` or :class:`ServerError`, see
:mod:`quotable.review.routing`; return a
:class:`Raw` for CSV, an image or a file) and add
``Route(method, pattern, func)`` to :data:`API_ROUTES`. The pattern is a regular expression
matched against the whole path; its groups reach ``request.params`` unquoted.

Every request is checked before it reaches a route: ``Host`` and ``Origin`` must be this server's
own address (so a web page in the same browser cannot use it), and a ``POST`` or ``PUT`` needs a
matching ``Origin``, ``Content-Type: application/json`` and a body of at most 64 KiB. Every
response carries the security headers and, when it is JSON, ``Cache-Control: no-store``. Errors
are ``{"error": "..."}`` with no stack trace.
"""

import json
import re
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit

from quotable.review.browse import ROUTES as BROWSE_ROUTES
from quotable.review.gold import ROUTES as GOLD_ROUTES
from quotable.review.review import ROUTES as REVIEW_ROUTES
from quotable.review.routing import (
    DEFAULT_MAX_BODY,
    BadRequest,
    NotFound,
    Raw,
    Request,
    Route,
    ServerError,
)

__all__ = [
    "API_ROUTES",
    "BadRequest",
    "NotFound",
    "Raw",
    "Request",
    "ReviewServer",
    "Route",
    "ServerError",
    "make_server",
]

API_ROUTES: list[Route] = [*BROWSE_ROUTES, *REVIEW_ROUTES, *GOLD_ROUTES]

MAX_BODY = DEFAULT_MAX_BODY  # a route may ask for more (Route.max_body)
_DRAIN_LIMIT = 1024 * 1024
_STATIC = resources.files("quotable.review").joinpath("static")
_STATIC_NAME = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]*")
_DIGITS = re.compile(r"[0-9]+")
_STATIC_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".svg": "image/svg+xml",
    ".json": "application/json",
    ".png": "image/png",
}
_SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; img-src 'self' blob:; frame-src 'self'; object-src 'self'; "
        "base-uri 'none'; form-action 'none'; frame-ancestors 'self'"
    ),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
}
_BODY_METHODS = ("POST", "PUT")


class _Refusal(Exception):  # noqa: N818
    """A request turned down by a check: the status and the message to send."""

    def __init__(self, status: HTTPStatus, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


class ReviewServer(ThreadingHTTPServer):
    """A server on 127.0.0.1 that knows the project folder, its routes and whether to log."""

    daemon_threads = True

    def __init__(
        self, project_dir: Path, port: int, routes: list[Route], *, verbose: bool = False
    ) -> None:
        """Bind 127.0.0.1:``port``; ``OSError`` if that cannot be done."""
        super().__init__(("127.0.0.1", port), _Handler)
        self.project_dir = project_dir
        self.routes = routes
        self.verbose = verbose

    @property
    def origins(self) -> tuple[str, ...]:
        """The origins the app's own pages have."""
        port = self.server_address[1]
        return (f"http://127.0.0.1:{port}", f"http://localhost:{port}")

    @property
    def hosts(self) -> tuple[str, ...]:
        """The ``Host`` values of requests to this server."""
        port = self.server_address[1]
        return (f"127.0.0.1:{port}", f"localhost:{port}")


def make_server(
    project_dir: Path, port: int, *, routes: list[Route] | None = None, verbose: bool = False
) -> ReviewServer:
    """Bind a server to 127.0.0.1:``port`` (0 picks a free port); ``OSError`` if it cannot."""
    return ReviewServer(
        project_dir, port, API_ROUTES if routes is None else routes, verbose=verbose
    )


class _Handler(BaseHTTPRequestHandler):
    server: ReviewServer
    _unread = 0

    def do_GET(self) -> None:  # noqa: N802
        self._handle("GET")

    def do_POST(self) -> None:  # noqa: N802
        self._handle("POST")

    def do_PUT(self) -> None:  # noqa: N802
        self._handle("PUT")

    def do_HEAD(self) -> None:  # noqa: N802
        self._handle("HEAD")

    def do_DELETE(self) -> None:  # noqa: N802
        self._handle("DELETE")

    def do_PATCH(self) -> None:  # noqa: N802
        self._handle("PATCH")

    def do_OPTIONS(self) -> None:  # noqa: N802
        self._handle("OPTIONS")

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        if self.server.verbose:
            super().log_message(format, *args)

    def send_error(self, code: int, message: str | None = None, explain: str | None = None) -> None:
        """Answer a malformed request in JSON like every other error."""
        self.log_error("code %d, message %s", code, message)
        self._send(code, json.dumps({"error": message or HTTPStatus(code).phrase}).encode(), "json")

    # --- one request ---
    def _handle(self, method: str) -> None:
        declared = self.headers.get("Content-Length", "")
        self._unread = int(declared) if _DIGITS.fullmatch(declared) else 0
        try:
            self._check_headers()
            path = urlsplit(self.path)
            self._answer(method, path.path, parse_qs(path.query, keep_blank_values=True))
        except _Refusal as refusal:
            self._send_json(refusal.status, {"error": refusal.message})
        except NotFound as err:
            self._send_json(HTTPStatus.NOT_FOUND, {"error": str(err)})
        except BadRequest as err:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(err)})
        except ServerError as err:
            self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(err)})
        except Exception as err:  # noqa: BLE001
            print(f"quotable: internal error on {method} {self.path}: {err!r}", file=sys.stderr)
            self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "internal error"})
        finally:
            self._drain()

    def _check_headers(self) -> None:
        if self.headers.get("Host") not in self.server.hosts:
            raise _Refusal(
                HTTPStatus.FORBIDDEN, "this server answers only to 127.0.0.1 or localhost"
            )
        origin = self.headers.get("Origin")
        if origin is not None and origin not in self.server.origins:
            raise _Refusal(HTTPStatus.FORBIDDEN, "request from another origin")

    def _answer(self, method: str, path: str, query: dict[str, list[str]]) -> None:
        if method == "GET" and (path == "/" or path.startswith("/static/")):
            self._send_static("index.html" if path == "/" else unquote(path[len("/static/") :]))
            return
        found = None
        known = path == "/" or path.startswith("/static/")
        for route in self.server.routes:
            groups = route.match(path)
            if groups is None:
                continue
            known = True
            if route.method == method:
                found = (route, tuple(unquote(g) for g in groups))
                break
        if found is None:
            if known:
                raise _Refusal(HTTPStatus.METHOD_NOT_ALLOWED, f"{method} is not allowed here")
            raise NotFound("not found")
        body = self._read_body(found[0].max_body) if method in _BODY_METHODS else None
        request = Request(self.server.project_dir, found[1], query, body)
        result = found[0].func(request)
        if isinstance(result, Raw):
            self._send(HTTPStatus.OK, result.body, result.content_type, result.headers)
        else:
            self._send_json(HTTPStatus.OK, result)

    def _read_body(self, max_body: int) -> Any:
        if self.headers.get("Origin") is None:
            raise _Refusal(HTTPStatus.FORBIDDEN, "a request that changes things needs an Origin")
        kind = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if kind != "application/json":
            raise _Refusal(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, "the body must be application/json")
        declared = self.headers.get("Content-Length")
        if declared is None:
            raise _Refusal(HTTPStatus.LENGTH_REQUIRED, "Content-Length is required")
        if not _DIGITS.fullmatch(declared):
            raise _Refusal(HTTPStatus.BAD_REQUEST, "Content-Length is not a number")
        length = int(declared)
        if length > max_body:
            raise _Refusal(
                HTTPStatus.REQUEST_ENTITY_TOO_LARGE, f"the body is over {max_body // 1024} KiB"
            )
        data = self.rfile.read(length)
        self._unread = 0
        try:
            return json.loads(data)
        except ValueError as err:
            raise BadRequest("the body is not valid JSON") from err

    def _drain(self) -> None:
        """Read a body that was refused, so closing the connection does not reset it."""
        if 0 < self._unread <= _DRAIN_LIMIT:
            self.rfile.read(self._unread)
        self._unread = 0

    # --- responses ---
    def _send_static(self, name: str) -> None:
        entry = _STATIC.joinpath(name) if _STATIC_NAME.fullmatch(name) else None
        if entry is None or not entry.is_file():
            raise NotFound("not found")
        kind = _STATIC_TYPES.get(Path(name).suffix, "application/octet-stream")
        self._send(HTTPStatus.OK, entry.read_bytes(), kind)

    def _send_json(self, status: int, data: Any) -> None:
        self._send(status, json.dumps(data).encode(), "json")

    def _send(
        self, status: int, body: bytes, kind: str, extra: dict[str, str] | None = None
    ) -> None:
        self.send_response(status)
        if kind == "json":
            self.send_header("Content-Type", "application/json")
        else:
            self.send_header("Content-Type", kind)
        if kind == "json" or extra is not None:
            self.send_header("Cache-Control", "no-store")
        for name, value in (extra or {}).items():
            self.send_header(name, value)
        for name, value in _SECURITY_HEADERS.items():
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
