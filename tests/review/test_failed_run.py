"""The review app opens a run that holds a failed table (spec 019, FR-011)."""

import threading
from collections.abc import Iterator
from pathlib import Path

import pytest

from quotable.review.server import make_server
from tests.review.test_browse_api import App, Built
from tests.test_failed_tables import HEADER_A, HEADER_C, PAGE_B, ROWS, a, bad, c, run
from tests.test_runs import save
from tests.test_tables import model


@pytest.fixture
def failed_app(make_pdf) -> Iterator[App]:
    path = make_pdf([HEADER_A, PAGE_B, HEADER_C])
    window = [[a()], [bad("B")], [c()]]
    tables, _ = run(path, model([window, window], ROWS))
    project = Path.cwd() / ".quotable"
    _, info, _, _ = save(project, tables, path)  # saving a failed table must not warn
    server = make_server(project, 0)
    thread = threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
    )
    thread.start()
    yield App(server, project, Built(project, {"failed": info.id}, {}))
    server.shutdown()
    server.server_close()
    thread.join()


def test_the_runs_list_and_the_run_open(failed_app):
    data = failed_app.json("/api/runs")
    assert data["total_runs"] == 1 and data["unreadable"] == 0
    (line,) = [r for d in data["documents"] for r in d["runs"]]
    assert line["tables"] == 3
    shown = failed_app.json(failed_app.run("failed"))
    assert len(shown["tables"]) == 3


def test_the_rows_of_every_table_open_the_failed_one_is_empty(failed_app):
    sound = failed_app.rows("failed", 0)
    assert sound["rows"]
    failed = failed_app.rows("failed", 1)
    assert failed["rows"] == []
    assert failed_app.rows("failed", 2)["rows"]


def test_the_csv_and_the_queue_open_too(failed_app):
    status, _, body = failed_app.get(f"{failed_app.run('failed')}/tables/1/rows.csv")
    assert status == 200 and len(body.strip().splitlines()) == 1  # the header line only
    status, _, _ = failed_app.get(f"{failed_app.run('failed')}/tables/0/rows.csv")
    assert status == 200
    assert failed_app.json(f"/api/queue?run={failed_app.id['failed']}")["counts"] is not None
