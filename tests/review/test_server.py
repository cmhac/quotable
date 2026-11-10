"""The review server (spec 013 task 006): the checks of section B, the routes, the static files."""

import http.client
import json
import threading
from collections.abc import Iterator
from importlib import resources
from pathlib import Path

import pytest

import quotable.review
from quotable.review.routing import BadRequest, NotFound, Raw, Request, Route, ServerError
from quotable.review.server import API_ROUTES, make_server

CSP = (
    "default-src 'self'; img-src 'self' blob:; frame-src 'self'; object-src 'self'; "
    "base-uri 'none'; form-action 'none'; frame-ancestors 'self'"
)


def echo(request: Request):
    return {
        "params": list(request.params),
        "query": request.query,
        "body": request.body,
        "project": str(request.project_dir),
    }


def missing(request: Request):
    raise NotFound("no such thing")


def refuse(request: Request):
    raise BadRequest("that is wrong")


def fail(request: Request):
    raise ServerError("the disk is full")


def explode(request: Request):
    msg = "secret internal detail"
    raise RuntimeError(msg)


def raw(request: Request):
    return Raw(b"a,b\r\n1,2\r\n", "text/csv; charset=utf-8", {"Content-Disposition": "attachment"})


ROUTES = [
    Route("GET", r"/api/echo/([a-z]+)/(\d+)", echo),
    Route("POST", r"/api/echo", echo),
    Route("PUT", r"/api/echo", echo),
    Route("PUT", r"/api/big", echo, max_body=200 * 1024),
    Route("GET", r"/api/missing", missing),
    Route("GET", r"/api/refuse", refuse),
    Route("GET", r"/api/explode", explode),
    Route("GET", r"/api/fail", fail),
    Route("GET", r"/api/raw", raw),
]


def serve(project: Path, **options):
    server = make_server(project, 0, **options)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


@pytest.fixture
def server(tmp_path) -> Iterator:
    running, thread = serve(tmp_path / ".quotable", routes=ROUTES)
    yield running
    running.shutdown()
    running.server_close()
    thread.join()


def origin(server) -> str:
    return f"http://127.0.0.1:{server.server_address[1]}"


def call(server, path, method="GET", headers=None, body=None):
    conn = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=5)
    try:
        conn.request(method, path, body=body, headers=headers or {})
        response = conn.getresponse()
        return response.status, response, response.read()
    finally:
        conn.close()


def post(server, path, payload, method="POST", **headers):
    base = {"Origin": origin(server), "Content-Type": "application/json"}
    data = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
    return call(server, path, method, {**base, **headers}, data)


def error_of(body: bytes) -> str:
    return json.loads(body)["error"]


# --- where it listens -------------------------------------------------------------------------
def test_the_server_listens_on_127_0_0_1_only(server):
    assert server.server_address[0] == "127.0.0.1"


def test_importing_the_package_starts_nothing():
    assert quotable.review.__doc__


# --- the index and the static files -----------------------------------------------------------
def test_the_index_is_served_with_the_security_headers(server):
    status, response, body = call(server, "/")
    assert status == 200
    assert response.getheader("Content-Type") == "text/html; charset=utf-8"
    assert response.getheader("Content-Security-Policy") == CSP
    assert response.getheader("X-Content-Type-Options") == "nosniff"
    assert response.getheader("Referrer-Policy") == "no-referrer"
    assert b"<html" in body


def test_a_static_file_is_served_by_name(server):
    status, response, body = call(server, "/static/index.html")
    assert status == 200
    assert response.getheader("Content-Security-Policy") == CSP
    assert body == call(server, "/")[2]


@pytest.mark.parametrize(
    "path",
    [
        "/static/../server.py",
        "/static/%2e%2e/x",
        "/static/%2e%2e%2fserver.py",
        "/static/..%2fserver.py",
        "/static/sub/index.html",
        "/static/nothing.js",
        "/static/",
        "/static/.hidden",
        "/static/%00",
        "/static/.",
    ],
)
def test_static_files_are_reached_by_name_only(server, path):
    status, _, body = call(server, path)
    assert status == 404
    assert error_of(body)


def test_the_static_files_are_readable_as_package_data():
    index = resources.files("quotable.review").joinpath("static", "index.html")
    assert index.read_text(encoding="utf-8").lstrip().lower().startswith("<!doctype html>")


def test_an_unknown_path_is_a_json_404_with_the_headers(server):
    status, response, body = call(server, "/nowhere")
    assert status == 404
    assert response.getheader("Content-Type") == "application/json"
    assert response.getheader("Content-Security-Policy") == CSP
    assert error_of(body)


# --- Host and Origin --------------------------------------------------------------------------
@pytest.mark.parametrize("host", ["evil.example", "127.0.0.1", "127.0.0.1:1", "example.com:80", ""])
def test_a_wrong_host_is_forbidden(server, host):
    status, response, body = call(server, "/", headers={"Host": host})
    assert status == 403
    assert response.getheader("Content-Security-Policy") == CSP
    assert error_of(body)


def test_localhost_is_an_allowed_host(server):
    port = server.server_address[1]
    assert call(server, "/", headers={"Host": f"localhost:{port}"})[0] == 200


def test_a_wrong_host_is_forbidden_on_the_api_too(server):
    assert call(server, "/api/missing", headers={"Host": "evil.example"})[0] == 403


@pytest.mark.parametrize(
    "bad", ["http://evil.example", "http://127.0.0.1:1", "null", "https://127.0.0.1", ""]
)
def test_a_foreign_origin_is_forbidden(server, bad):
    assert call(server, "/", headers={"Origin": bad})[0] == 403
    assert call(server, "/api/missing", headers={"Origin": bad})[0] == 403


def test_the_own_origins_are_allowed(server):
    port = server.server_address[1]
    for name in ("127.0.0.1", "localhost"):
        status, _, _ = call(server, "/", headers={"Origin": f"http://{name}:{port}"})
        assert status == 200


# --- POST and PUT -----------------------------------------------------------------------------
def test_a_post_with_the_right_origin_and_json_reaches_its_function(server):
    status, response, body = post(server, "/api/echo", {"a": [1, 2]})
    assert status == 200
    assert response.getheader("Content-Type") == "application/json"
    assert json.loads(body)["body"] == {"a": [1, 2]}


def test_a_put_is_checked_like_a_post(server):
    assert post(server, "/api/echo", {"a": 1}, method="PUT")[0] == 200
    status, _, _ = call(server, "/api/echo", "PUT", {"Content-Type": "application/json"}, b"{}")
    assert status == 403


def test_a_post_without_origin_is_forbidden(server):
    status, _, body = call(
        server, "/api/echo", "POST", {"Content-Type": "application/json"}, b'{"a": 1}'
    )
    assert status == 403
    assert error_of(body)


def test_a_post_with_a_foreign_origin_is_forbidden(server):
    assert post(server, "/api/echo", {}, Origin="http://evil.example")[0] == 403


@pytest.mark.parametrize("kind", ["text/plain", "application/x-www-form-urlencoded", ""])
def test_a_post_that_is_not_json_is_refused(server, kind):
    status, _, body = post(server, "/api/echo", {"a": 1}, **{"Content-Type": kind})
    assert status == 415
    assert error_of(body)


def test_a_json_content_type_may_carry_a_charset(server):
    kind = "application/json; charset=utf-8"
    assert post(server, "/api/echo", {"a": 1}, **{"Content-Type": kind})[0] == 200


def test_a_body_of_64_kib_is_accepted_and_one_byte_more_is_not(server):
    ok = b'"' + b"x" * (64 * 1024 - 2) + b'"'
    assert len(ok) == 64 * 1024
    assert post(server, "/api/echo", ok)[0] == 200
    assert post(server, "/api/echo", ok + b" ")[0] == 413


def test_a_body_of_100_kib_is_refused(server):
    status, _, body = post(server, "/api/echo", b'"' + b"x" * (100 * 1024) + b'"')
    assert status == 413
    assert error_of(body)


def test_a_route_can_ask_for_a_bigger_body_and_others_keep_the_old_limit(server):
    big = b'"' + b"x" * (100 * 1024) + b'"'
    assert post(server, "/api/big", big, method="PUT")[0] == 200
    assert post(server, "/api/big", big + b"x" * (120 * 1024), method="PUT")[0] == 413
    assert post(server, "/api/echo", big, method="PUT")[0] == 413


def test_a_huge_declared_length_is_refused_without_being_read(server):
    conn = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=5)
    try:
        conn.putrequest("POST", "/api/echo")
        conn.putheader("Origin", origin(server))
        conn.putheader("Content-Type", "application/json")
        conn.putheader("Content-Length", str(10**12))
        conn.endheaders()
        assert conn.getresponse().status == 413
    finally:
        conn.close()


def test_a_post_without_a_length_is_refused(server):
    conn = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=5)
    try:
        conn.putrequest("POST", "/api/echo")
        conn.putheader("Origin", origin(server))
        conn.putheader("Content-Type", "application/json")
        conn.endheaders()
        assert conn.getresponse().status == 411
    finally:
        conn.close()


@pytest.mark.parametrize("body", [b"{broken", b"", b"\xff\xfe"])
def test_a_body_that_is_not_json_is_a_bad_request(server, body):
    status, _, text = post(server, "/api/echo", body)
    assert status == 400
    assert error_of(text)


def test_a_post_to_a_get_only_route_is_405(server):
    status, _, body = post(server, "/api/missing", {})
    assert status == 405
    assert error_of(body)


def test_a_post_to_a_static_file_is_405(server):
    assert post(server, "/static/index.html", {})[0] == 405
    assert post(server, "/", {})[0] == 405


def test_other_methods_are_refused(server):
    status, _, _ = call(server, "/api/echo", "DELETE", {"Origin": origin(server)})
    assert status == 405


# --- the route table --------------------------------------------------------------------------
def test_a_route_gets_unquoted_groups_the_query_and_the_project_dir(server, tmp_path):
    status, response, body = call(server, "/api/echo/abc/12?x=1&x=2&y=%C3%A9&blank=")
    assert status == 200
    assert response.getheader("Cache-Control") == "no-store"
    assert json.loads(body) == {
        "params": ["abc", "12"],
        "query": {"x": ["1", "2"], "y": ["é"], "blank": [""]},
        "body": None,
        "project": str(tmp_path / ".quotable"),
    }


def test_a_raw_response_is_sent_as_it_is_with_its_headers_and_the_security_headers(server):
    status, response, body = call(server, "/api/raw")
    assert status == 200
    assert body == b"a,b\r\n1,2\r\n"
    assert response.getheader("Content-Type") == "text/csv; charset=utf-8"
    assert response.getheader("Content-Disposition") == "attachment"
    assert response.getheader("Content-Length") == str(len(body))
    assert response.getheader("Cache-Control") == "no-store"
    assert response.getheader("Content-Security-Policy") == CSP
    assert response.getheader("X-Content-Type-Options") == "nosniff"


def test_the_whole_path_must_match_a_route(server):
    assert call(server, "/api/echo/abc/12/more")[0] == 404
    assert call(server, "/api/echo/ABC/12")[0] == 404
    assert call(server, "/x/api/echo/abc/12")[0] == 404


def test_not_found_and_bad_request_become_json_errors(server):
    status, response, body = call(server, "/api/missing")
    assert (status, error_of(body)) == (404, "no such thing")
    assert response.getheader("Cache-Control") == "no-store"
    status, _, body = call(server, "/api/refuse")
    assert (status, error_of(body)) == (400, "that is wrong")


def test_a_server_error_is_a_500_with_its_own_message(server):
    status, response, body = call(server, "/api/fail")
    assert (status, error_of(body)) == (500, "the disk is full")
    assert response.getheader("Content-Security-Policy") == CSP
    assert response.getheader("Cache-Control") == "no-store"


def test_an_unexpected_error_is_a_500_without_a_trace(server, capsys):
    status, response, body = call(server, "/api/explode")
    assert status == 500
    assert json.loads(body) == {"error": "internal error"}
    assert response.getheader("Content-Security-Policy") == CSP
    assert "secret internal detail" not in body.decode()
    assert "Traceback" not in body.decode()


def test_the_default_routes_are_the_api_routes_of_the_package():
    assert isinstance(API_ROUTES, list)
    assert all(isinstance(route, Route) for route in API_ROUTES)


# --- logging ----------------------------------------------------------------------------------
def test_requests_are_not_logged_by_default(server, capsys):
    call(server, "/")
    assert capsys.readouterr().err == ""


def test_requests_are_logged_to_stderr_with_verbose(tmp_path, capsys):
    running, thread = serve(tmp_path, routes=ROUTES, verbose=True)
    try:
        call(running, "/")
    finally:
        running.shutdown()
        running.server_close()
        thread.join()
    captured = capsys.readouterr()
    assert captured.out == ""
    assert '"GET / HTTP/1.1" 200' in captured.err
