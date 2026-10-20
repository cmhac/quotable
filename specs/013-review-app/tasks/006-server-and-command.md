# 006 - `quotable review`: the command and a locked-down server

Spec: `../spec.md` (Requirements B1 to B7). Depends on: task 002.

## Goal

`quotable review` starts a standard-library HTTP server on 127.0.0.1 that serves the static
files of the app and a JSON API (filled in by tasks 007 and 008), with every check of section B
in one place.

## Steps

1. Red first: tests in `tests/review/test_server.py` and `tests/test_cli.py` (step 6).
2. `quotable/review/server.py`:
   - `make_server(project_dir, port) -> ThreadingHTTPServer` bound to `("127.0.0.1", port)`
     (port 0 in the tests), and a `Handler` with a small route table: `GET /` and
     `GET /static/<name>` (only files that exist in `quotable/review/static/`, by name, no
     sub-paths), `GET /api/...` and `POST /api/...` dispatched to functions that take parsed
     arguments and return JSON-able data or raise `NotFound` / `BadRequest`.
   - Every request: `Host` must be `127.0.0.1:<port>` or `localhost:<port>`, else 403. A
     request with an `Origin` header must have one of the two origins, else 403. A `POST` must
     have a matching `Origin` and `Content-Type: application/json`, and a body of at most
     64 KiB (413 otherwise).
   - Every response: `Content-Security-Policy: default-src 'self'; img-src 'self' blob:;
frame-src 'self'; object-src 'self'; base-uri 'none'; form-action 'none';
frame-ancestors 'self'`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`,
     `Cache-Control: no-store` for the API.
   - Errors return JSON `{"error": "..."}` with no stack trace; the server logs one line per
     request to stderr only with `--verbose` (default quiet).
3. `quotable/review/static/index.html` with the header bar only (task 010 fills it), so the
   server has something to serve.
4. `__main__.py`: a `review` sub-command with `--dir`, `--port` (default 8765), `--no-browser`,
   `--run ID`, `--verbose`. It prints `Serving the review app at http://127.0.0.1:<port> (Ctrl+C
to stop)` and `Runs: N in .quotable/runs/` (or how to make one), opens the browser with
   `webbrowser.open` unless `--no-browser` (with `--run`, on that run), and serves until Ctrl+C,
   then exits 0. A taken port (`OSError` with `EADDRINUSE`) exits 1 with
   `quotable: port 8765 is in use; try --port`. An unknown `--run` id exits 1. The module
   docstring lists the new command and its exit codes. Importing `quotable.review` must not
   start anything.
5. `pyproject.toml`: confirm `uv build` puts `quotable/review/static/*` in the wheel (the
   trigram JSON already ships this way); a test reads the files through
   `importlib.resources`.
6. Tests: the server on port 0 in a thread, requests with `http.client`:
   - `GET /` 200 with the security headers; a wrong `Host` 403; a foreign `Origin` 403; a POST
     without `Origin`, with `text/plain` or with a 100 KiB body refused;
     `/static/../server.py`, `/static/%2e%2e/x` and an unknown name 404;
   - `main(["review", "--port", <taken port>, "--no-browser"])` returns 1 with the message;
     `--help` lists the options; `cost-report` still works;
   - the server never listens on another address (check `server.server_address`).
7. `ruff check`, `ruff format`, `ty check`, `just test`.

## Done when

The command starts and stops cleanly, every check of B2, B5 and B7 has a test, and the suite
passes.
