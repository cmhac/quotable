"""The browsing API (spec 013 task 007): runs, tables, cells, pages, PDF and CSV, over HTTP."""

import csv
import hashlib
import http.client
import io
import json
import shutil
import threading
from collections import Counter
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

import pymupdf
import pytest

from quotable import extract_tables
from quotable import pipeline as pipeline_module
from quotable.llm.answers import PageRecheck
from quotable.review import sources
from quotable.review.queue import FLAGGED, QueueSettings, population
from quotable.review.server import make_server
from quotable.review.verdicts import CellKey, DraftStore, ExtraKey, Verdict, VerdictStore
from quotable.runs import load_run
from quotable.steps import extract
from quotable.steps.grounding import UNFLAGGED
from quotable.table import Table
from tests.conftest import FakeClient
from tests.extra_fields_model import request_for, truth_model
from tests.fixture_tables import DATA as FIXTURE
from tests.fixture_tables import load_doc
from tests.test_entrypoint import PDF as SIMPLE_PDF
from tests.test_entrypoint import Calls
from tests.test_merge_pipeline import client_for
from tests.test_senate_tables import PDF as SENATE_PDF
from tests.test_senate_tables import recorded_model

STARTED = {
    "simple_old": "2026-10-19T16:40:00Z",
    "simple_new": "2026-10-20T10:14:00Z",
    "senate": "2026-10-18T09:00:00Z",
    "merged": "2026-10-17T09:00:00Z",
    "extras": "2026-10-16T09:00:00Z",
    "clears": "2026-10-15T09:00:00Z",
}
RUN_FILE, TABLES_FILE = "run.json", "tables.json"


# --- a project built by the real pipeline, once ------------------------------------------------
@dataclass
class Built:
    project: Path
    runs: dict[str, str]  # label -> run id
    tables: dict[str, list[Table]]


def edit_run(
    project: Path,
    run_id: str,
    small: Callable[[dict], object] | None = None,
    big: Callable[[dict], object] | None = None,
) -> None:
    folder = project / "runs" / run_id
    for name, change in ((RUN_FILE, small), (TABLES_FILE, big)):
        if change is not None:
            data = json.loads((folder / name).read_text(encoding="utf-8"))
            change(data)
            (folder / name).write_text(json.dumps(data), encoding="utf-8")


def new_run(project: Path, known: set[str]) -> str:
    (found,) = {p.name for p in (project / "runs").iterdir()} - known
    return found


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> Built:
    work = tmp_path_factory.mktemp("browse")
    project = work / ".quotable"
    runs: dict[str, str] = {}
    tables: dict[str, list[Table]] = {}

    def folders() -> set[str]:
        return (
            {p.name for p in (project / "runs").iterdir()} if (project / "runs").exists() else set()
        )

    with pytest.MonkeyPatch.context() as mp:
        mp.chdir(work)
        # two runs of one page: the first pays (no known price), the second is all cache hits
        before = folders()
        tables["simple_old"] = extract_tables(SIMPLE_PDF, Calls().model(), recheck=False)
        runs["simple_old"] = new_run(project, before)
        before = folders()
        tables["simple_new"] = extract_tables(SIMPLE_PDF, Calls().model(), recheck=False)
        runs["simple_new"] = new_run(project, before)

        def with_client(label: str, client: FakeClient, pdf: Path, **options: Any) -> None:
            mp.setattr(pipeline_module, "PydanticAIClient", lambda *a, **k: client)
            before = folders()
            tables[label] = extract_tables(pdf, f"test:{label}", ocr=False, **options)
            runs[label] = new_run(project, before)

        with_client("senate", recorded_model(), SENATE_PDF, recheck=False)

        truth = load_doc("pipe-reworded-gap1")
        names, b_names = truth["parts"][0]["columns"], truth["parts"][1]["columns"]
        correct = truth["parts"][1]["rows"]["5"][2][0]
        wrong = correct.split()[0] + " Zzyzx"

        def recheck(request: Any) -> PageRecheck:  # noqa: ANN401
            return PageRecheck(cells=[{"row": 3, "column": names[0], "value": correct}])

        client, _ = client_for(
            "pipe-reworded-gap1", typos={(5, 3, b_names[0]): wrong}, recheck=recheck
        )
        with_client("merged", client, FIXTURE / "pipe-reworded-gap1.pdf", discovery_pages=1)

        for label, case in (("extras", "extra-section-3p"), ("clears", "extra-group-clears")):
            extra = load_doc(case)["extra_fields"]
            with_client(
                label,
                truth_model(case),
                FIXTURE / f"{case}.pdf",
                recheck=False,
                extra_fields=request_for(extra, carry=True),
            )
    for label, run_id in runs.items():
        edit_run(project, run_id, lambda d, label=label: d["run"].update(started=STARTED[label]))
    return Built(project, runs, tables)


class App:
    def __init__(self, server: Any, project: Path, built: Built) -> None:
        self.server, self.project, self.built = server, project, built
        self.id = built.runs

    def get(self, path: str, headers: dict[str, str] | None = None):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_address[1], timeout=10)
        path = quote(path, safe="/?&=,%:()$+")  # tests write names with spaces
        try:
            conn.request("GET", path, headers=headers or {})
            response = conn.getresponse()
            return response.status, response, response.read()
        finally:
            conn.close()

    def json(self, path: str) -> Any:
        status, _, body = self.get(path)
        assert status == 200, (path, status, body[:300])
        return json.loads(body)

    def error(self, path: str, status: int = 404) -> str:
        got, response, body = self.get(path)
        assert got == status, (path, got, body[:200])
        assert response.getheader("Content-Type") == "application/json"
        return json.loads(body)["error"]

    def run(self, label: str) -> str:
        return f"/api/runs/{self.id[label]}"

    def rows(self, label: str, table: int = 0, query: str = "") -> dict:
        return self.json(f"{self.run(label)}/tables/{table}/rows{'?' + query if query else ''}")


@pytest.fixture
def app(built: Built) -> Iterator[App]:
    project = Path.cwd() / ".quotable"
    shutil.copytree(built.project, project)
    server = make_server(project, 0)
    thread = threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
    )
    thread.start()
    yield App(server, project, built)
    server.shutdown()
    server.server_close()
    thread.join()


def snapshot(folder: Path) -> dict[str, tuple[int, int, str]]:
    return {
        str(p.relative_to(folder)): (
            p.stat().st_size,
            p.stat().st_mtime_ns,
            hashlib.sha256(p.read_bytes()).hexdigest(),
        )
        for p in sorted(folder.rglob("*"))
        if p.is_file()
    }


# --- verdict helpers ---------------------------------------------------------------------------
def give(  # noqa: PLR0913, PLR0917
    app: App,
    label: str,
    table: int,
    page: int,
    row: int,
    column: str,
    kind: str = "correct",
    *,
    judged: str | None = None,
    note: str = "",
) -> None:
    run = load_run(app.project, app.id[label])
    t = run.tables[table]
    value = next(r.values[column] for r in t.rows if (r.page, r.row) == (page, row))
    cell = next(r for r in t.rows if (r.page, r.row) == (page, row)).cells[column]
    changed = kind == "changed"
    VerdictStore(app.project).append(
        Verdict(
            time="2026-10-20T12:00:00Z",
            run=run.summary.id,
            name=run.summary.name,
            table_index=t.index,
            table_label=t.label,
            table_columns=tuple(t.columns),
            key=CellKey(run.summary.sha256, tuple(t.columns), page, row, column),
            extracted=value if judged is None else judged,
            status=cell.status,
            verdict=kind,
            value="other" if changed else None,
            category="other" if changed else None,
            note=note,
        )
    )


def flagged_rows(app: App, label: str, table: int) -> list[tuple[int, int, list[str]]]:
    rows = app.rows(label, table, "flagged=1&offset=0")
    return [
        (r["page"], r["row"], [c["name"] for c in r["cells"] if c["status"] not in UNFLAGGED])
        for r in rows["rows"]
    ]


# --- the runs list -----------------------------------------------------------------------------
def test_runs_are_grouped_by_document_with_the_newest_run_first(app):
    data = app.json("/api/runs")
    names = [d["name"] for d in data["documents"]]
    assert names[0] == SIMPLE_PDF.name  # its newest run is the newest of all
    simple = data["documents"][0]
    assert [r["id"] for r in simple["runs"]] == [app.id["simple_new"], app.id["simple_old"]]
    assert simple["sha256"] == hashlib.sha256(SIMPLE_PDF.read_bytes()).hexdigest()
    assert simple["sha_short"] == f"{simple['sha256'][:4]}…{simple['sha256'][-4:]}"
    assert simple["pages"] == 1
    assert simple["size"] == SIMPLE_PDF.stat().st_size
    assert (data["total_runs"], data["total_documents"], data["runs"]) == (6, 5, 6)
    assert data["project"] == str(app.project)
    assert data["unreadable"] == 0


def test_a_run_line_has_the_counts_of_the_run(app):
    data = app.json("/api/runs")
    senate = next(r for d in data["documents"] for r in d["runs"] if r["id"] == app.id["senate"])
    summary = load_run(app.project, app.id["senate"]).summary
    assert senate["short_id"] == summary.id[:8]
    assert senate["started"] == STARTED["senate"]
    assert senate["model"] == "test:senate"
    assert senate["tables"] == 2
    assert senate["rows"] == summary.rows
    assert senate["cells"] == summary.cells
    assert senate["flagged"] == summary.flagged == {"ungrounded": 74, "misplaced": 1}
    assert senate["flagged_total"] == 75
    assert senate["ocr_pages"] == []
    assert senate["review"] == {"reviewed": 0, "flagged": 75, "done": False}


def test_the_models_for_the_filter_are_listed_whatever_the_filter(app):
    data = app.json("/api/runs?model=test:senate")
    assert data["models"] == [
        "function:entrypoint-test",
        "test:clears",
        "test:extras",
        "test:merged",
        "test:senate",
    ]
    assert data["runs"] == 1
    assert [r["id"] for d in data["documents"] for r in d["runs"]] == [app.id["senate"]]
    assert data["total_runs"] == 6


def test_the_document_filter_matches_the_file_name_in_any_case(app):
    data = app.json("/api/runs?document=MILCON")
    assert [d["name"] for d in data["documents"]] == [SIMPLE_PDF.name]
    assert data["runs"] == 2
    assert app.json("/api/runs?document=nothing-like-it")["documents"] == []
    both = app.json("/api/runs?document=milcon&model=function:entrypoint-test")
    assert both["runs"] == 2


def test_an_unreadable_run_is_counted(app):
    bad = app.project / "runs" / ("ab" * 16)
    bad.mkdir()
    (bad / RUN_FILE).write_text("{not json")
    assert app.json("/api/runs")["unreadable"] == 1


def test_costs_come_from_the_cost_log(app):
    first, second = app.id["simple_old"], app.id["simple_new"]
    lines = (app.project / "cost" / "requests.jsonl").read_text().splitlines()
    assert {json.loads(x)["run"] for x in lines} == {first}  # the second run was all cache hits

    def record(run: str, cost: float | None) -> str:
        data = {**json.loads(lines[0]), "run": run, "cost_usd": cost}
        return json.dumps(data)

    runs = app.json("/api/runs")["documents"][0]["runs"]
    assert [r["cost"] for r in runs] == [{"kind": "free"}, {"kind": "unknown"}]  # no price known
    senate = app.id["senate"]
    (app.project / "cost" / "requests.jsonl").write_text(
        "\n".join(
            [record(senate, 0.25), record(senate, 0.125), record(first, 0.5), record(first, None)]
        )
        + "\n"
    )
    found = {r["id"]: r["cost"] for d in app.json("/api/runs")["documents"] for r in d["runs"]}
    assert found[senate] == {"kind": "usd", "usd": 0.375}
    assert found[first] == {"kind": "unknown"}
    assert found[second] == {"kind": "free"}
    assert app.json(app.run("senate"))["cost"] == {"kind": "usd", "usd": 0.375}


def test_review_progress_counts_the_flagged_cells_with_a_current_verdict(app):
    items = population(
        [load_run(app.project, app.id["senate"])],
        QueueSettings(statuses=FLAGGED, run=app.id["senate"], table=1),
    )
    first, second, third = items[:3]
    for item, kind, judged in (
        (first, "correct", None),
        (second, "changed", None),
        (third, "unsure", "old"),
    ):
        give(app, "senate", 1, item.page, item.row or 0, item.column, kind, judged=judged)
    run = next(
        r
        for d in app.json("/api/runs")["documents"]
        for r in d["runs"]
        if r["id"] == app.id["senate"]
    )
    assert run["review"] == {"reviewed": 2, "flagged": 75, "done": False}  # the third is stale
    assert app.json(app.run("senate"))["review"]["reviewed"] == 2


def test_a_run_whose_every_flagged_cell_has_a_verdict_is_done(app):
    for item in population(
        [load_run(app.project, app.id["senate"])],
        QueueSettings(statuses=FLAGGED, run=app.id["senate"]),
    ):
        give(app, "senate", item.table_index, item.page, item.row or 0, item.column)
    assert app.json(app.run("senate"))["review"] == {"reviewed": 75, "flagged": 75, "done": True}


# --- one run -----------------------------------------------------------------------------------
def test_a_run_has_its_fields_settings_document_and_tables(app):
    data = app.json(app.run("senate"))
    summary = load_run(app.project, app.id["senate"]).summary
    assert data["id"] == summary.id
    assert data["short_id"] == summary.id[:8]
    assert (data["started"], data["model"]) == (STARTED["senate"], "test:senate")
    assert data["format"] == 1
    assert data["quotable"] == summary.quotable
    assert data["settings"]["recheck"] is False
    assert data["settings"]["discovery_pages"] == summary.settings["discovery_pages"]
    assert data["document"] == {
        "name": SENATE_PDF.name,
        "path": str(SENATE_PDF.resolve()),
        "size": SENATE_PDF.stat().st_size,
        "sha256": summary.sha256,
        "sha_short": f"{summary.sha256[:4]}…{summary.sha256[-4:]}",
        "pages": 3,
    }
    assert data["pdf"] == {"status": "ok", "path": str(SENATE_PDF.resolve())}
    assert data["summary"]["tables"] == 2
    assert data["summary"]["flagged"] == {"ungrounded": 74, "misplaced": 1}
    first, second = data["tables"]
    assert (first["index"], first["number"], first["label"]) == (0, 1, "Expenditure summary")
    assert (second["index"], second["number"], second["label"]) == (1, 2, "Expenditure detail")
    assert second["pages"] == [1, 2, 3]
    assert second["rows"] == 124
    assert second["flagged"] == {"ungrounded": 74, "misplaced": 1}
    assert second["columns"][0] == "DOCUMENT NO."
    assert (second["merged"], second["ocr_pages"]) == (0, [])


def test_the_extra_fields_of_a_run_are_in_its_settings(app):
    settings = app.json(app.run("extras"))["settings"]
    assert settings["extra_fields"]["carry_forward"] is True
    assert [f["name"] for f in settings["extra_fields"]["fields"]] == ["division"]
    assert app.json(app.run("extras"))["tables"][0]["extra_names"] == ["division"]


def test_a_page_shared_by_two_tables_is_noted_for_each(app):
    first, second = app.json(app.run("senate"))["tables"]
    assert first["note"] == [
        {
            "kind": "shared",
            "page": 1,
            "tables": [2],
            "text": "Shares p. 1 with Table 2; each has its own band of the page",
        }
    ]
    assert (
        second["note"][0]["text"] == "Shares p. 1 with Table 1; each has its own band of the page"
    )


def test_a_merged_table_notes_its_parts_and_the_accepted_recheck_changes(app):
    (table,) = app.json(app.run("merged"))["tables"]
    truth = load_doc("pipe-reworded-gap1")
    parts = [n for n in table["note"] if n["kind"] == "merged"]
    assert len(parts) == 1
    assert parts[0]["pages"] == [4, 5]
    assert parts[0]["columns"] == truth["parts"][1]["columns"]
    assert (
        parts[0]["text"]
        == f"Merged part: pp. 4–5, columns {' · '.join(truth['parts'][1]['columns'])}"
    )
    changes = [n for n in table["note"] if n["kind"] == "changes"]
    assert changes == [{"kind": "changes", "count": 1, "text": "1 recheck change accepted"}]
    assert table["merged"] == 1
    assert table["pages"] == [1, 2, 4, 5]


def test_a_table_with_nothing_to_note_has_an_empty_note(app):
    assert app.json(app.run("simple_new"))["tables"][0]["note"] == []


def test_ocr_pages_are_listed_for_a_run_and_its_tables(app):
    run_id = app.id["senate"]
    edit_run(
        app.project,
        run_id,
        small=lambda d: (
            d["summary"].update(ocr_pages=[1]),
            d["tables"][0].update(ocr_pages=[1]),
        ),
    )
    data = app.json(app.run("senate"))
    assert data["summary"]["ocr_pages"] == [1]
    assert data["tables"][0]["ocr_pages"] == [1]
    listed = next(
        r for d in app.json("/api/runs")["documents"] for r in d["runs"] if r["id"] == run_id
    )
    assert listed["ocr_pages"] == [1]


def own_copy(app: App, tmp_path: Path) -> tuple[Path, str]:
    """Make a run of a private copy of the sample PDF, so a test can change the file."""
    copy = tmp_path / "copy.pdf"
    shutil.copy(SIMPLE_PDF, copy)
    known = {p.name for p in (app.project / "runs").iterdir()}
    extract_tables(copy, Calls().model(), recheck=False)
    return copy, new_run(app.project, known)


def test_a_missing_pdf_is_reported_with_its_path(app, tmp_path):
    copy, run_id = own_copy(app, tmp_path)
    assert app.json(f"/api/runs/{run_id}")["pdf"] == {"status": "ok", "path": str(copy.resolve())}
    copy.unlink()
    assert app.json(f"/api/runs/{run_id}")["pdf"] == {
        "status": "missing",
        "path": str(copy.resolve()),
    }
    assert "missing" in app.error(f"/api/runs/{run_id}/pages/1.png")
    assert "missing" in app.error(f"/api/runs/{run_id}/pdf")
    assert app.json(f"/api/runs/{run_id}/tables/0/rows")["rows"]  # the rest still works


def test_a_changed_pdf_is_reported_with_both_short_hashes(app, tmp_path):
    copy, run_id = own_copy(app, tmp_path)
    expected = hashlib.sha256(copy.read_bytes()).hexdigest()
    copy.write_bytes(copy.read_bytes() + b"\n%changed\n")
    found = hashlib.sha256(copy.read_bytes()).hexdigest()
    pdf = app.json(f"/api/runs/{run_id}")["pdf"]
    assert pdf == {
        "status": "changed",
        "path": str(copy.resolve()),
        "expected": f"{expected[:4]}…{expected[-4:]}",
        "found": f"{found[:4]}…{found[-4:]}",
    }
    assert "changed" in app.error(f"/api/runs/{run_id}/pages/1.png")
    assert "changed" in app.error(f"/api/runs/{run_id}/pdf")


def test_the_pdf_is_hashed_once_per_path_size_and_modification_time(app, tmp_path, monkeypatch):
    copy, run_id = own_copy(app, tmp_path)
    calls = []
    real = sources.file_sha256

    def counting(path):
        calls.append(path)
        return real(path)

    monkeypatch.setattr(sources, "file_sha256", counting)
    for _ in range(3):
        assert app.json(f"/api/runs/{run_id}")["pdf"]["status"] == "ok"
    assert len(calls) == 1
    copy.write_bytes(copy.read_bytes() + b"\n%changed\n")
    assert app.json(f"/api/runs/{run_id}")["pdf"]["status"] == "changed"
    assert len(calls) == 2


@pytest.mark.parametrize(
    "path",
    [
        "/api/runs/" + "0" * 32,
        "/api/runs/nothing",
        "/api/runs/..",
        "/api/runs/%2e%2e",
        "/api/runs/..%2fruns",
        "/api/runs/" + "0" * 32 + "/tables/0/rows",
        "/api/runs/" + "0" * 32 + "/pdf",
    ],
)
def test_an_unknown_run_is_404(app, path):
    assert app.error(path)


# --- the rows of a table -----------------------------------------------------------------------
def test_a_page_of_rows_has_the_columns_the_cells_and_the_counts(app):
    data = app.rows("simple_new")
    table = app.built.tables["simple_new"][0]
    assert (data["offset"], data["limit"]) == (0, 100)
    assert data["matched"] == data["total"] == len(table.rows()) == len(data["rows"])
    assert [c["key"] for c in data["columns"]] == ["page", "row", *table.columns]
    assert [c["kind"] for c in data["columns"]] == ["page", "row"] + ["column"] * 5
    first = data["rows"][0]
    assert (first["page"], first["row"]) == (1, 1)
    assert [c["name"] for c in first["cells"]] == table.columns
    assert [c["value"] for c in first["cells"]] == list(table.rows()[0].values.values())
    assert first["cells"][0] == {
        "key": "Account",
        "name": "Account",
        "extra": False,
        "value": "Air National Guard",
        "status": "exact",
        "coverage": table.rows()[0].cells["Account"].coverage,
        "source_page": None,
        "state": "none",
    }
    assert first["status"] == "exact"
    assert (first["recheck"], first["ocr"], first["merged"]) == (False, False, False)


def test_rows_come_in_pages_of_100_from_the_offset(app):
    full = app.rows("senate", 1)
    assert (full["total"], full["matched"], len(full["rows"])) == (124, 124, 100)
    second = app.rows("senate", 1, "offset=100")
    assert second["offset"] == 100
    assert [(r["page"], r["row"]) for r in second["rows"]] == [
        (r.page, r.row) for r in app.built.tables["senate"][1].rows()[100:]
    ]
    assert app.rows("senate", 1, "offset=124")["rows"] == []
    assert app.rows("senate", 1, "offset=5000")["rows"] == []
    assert app.rows("senate", 1, "offset=5000")["matched"] == 124


@pytest.mark.parametrize(
    "query",
    [
        "offset=-1",
        "offset=x",
        "offset=1.5",
        "status=bogus",
        "page=x",
        "review=maybe",
        "sort=nope",
        "column=nope",
    ],
)
def test_a_query_that_cannot_be_used_is_a_400(app, query):
    assert app.error(f"{app.run('senate')}/tables/1/rows?{query}", 400)


def test_the_summary_counts_cells_by_status_per_column_and_by_position(app):
    data = app.rows("senate", 1)
    summary = data["summary"]
    assert list(summary["statuses"])[:7] == [
        "exact",
        "fuzzy",
        "misplaced",
        "ungrounded",
        "untokenized",
        "empty",
        "not_on_page",
    ]
    assert summary["statuses"] == {
        "exact": 295,
        "fuzzy": 0,
        "misplaced": 1,
        "ungrounded": 74,
        "untokenized": 0,
        "empty": 498,
        "not_on_page": 0,
    }
    assert summary["cells"] == 124 * 7
    assert summary["position"] == {"misplaced": 1, "unchecked": 0}
    assert summary["recheck"] == {"accepted": 0}
    amount = next(c for c in data["columns"] if c["key"] == "AMOUNT ($)")
    in_table = Counter(r.cells["AMOUNT ($)"].status for r in app.built.tables["senate"][1].rows())
    assert amount["statuses"] == dict(in_table)
    assert amount["statuses"]["ungrounded"] == 61
    assert next(c for c in data["columns"] if c["key"] == "page")["statuses"] == {}
    assert sum(sum(c["statuses"].values()) for c in data["columns"]) == 124 * 7


def test_the_summary_counts_the_accepted_recheck_changes(app):
    assert app.rows("merged")["summary"]["recheck"] == {"accepted": 1}


def test_numeric_columns_are_the_ones_whose_values_mostly_parse_as_numbers(app):
    columns = {c["key"]: c["numeric"] for c in app.rows("simple_new")["columns"]}
    assert columns == {
        "page": True,
        "row": True,
        "Account": False,
        "Location": False,
        "Project": False,
        "Amount": True,
        "Requestor(s)": False,
    }
    detail = {c["key"]: c["numeric"] for c in app.rows("senate", 1)["columns"]}
    assert detail["AMOUNT ($)"] is True
    assert detail["PAYEE NAME"] is False
    assert detail["DOCUMENT NO."] is False  # mostly empty, nothing to go on


def test_a_status_filter_matches_rows_with_a_cell_of_a_chosen_status(app):
    ungrounded = app.rows("senate", 1, "status=ungrounded")
    assert ungrounded["matched"] == 67  # 74 ungrounded cells, some rows have two
    assert all("ungrounded" in [c["status"] for c in r["cells"]] for r in ungrounded["rows"])
    either = app.rows("senate", 1, "status=ungrounded,misplaced")
    assert either["matched"] == 68
    assert app.rows("senate", 1, "status=misplaced&status=ungrounded")["matched"] == 68
    assert app.rows("senate", 1, "")["matched"] == 124  # no status means any


def test_a_status_filter_with_a_column_looks_at_that_columns_cell_only(app):
    assert app.rows("senate", 1, "status=empty&column=DOCUMENT NO.")["matched"] > 0
    only = app.rows("senate", 1, "status=ungrounded&column=PAYEE NAME")
    assert only["matched"] == 13
    amount = app.rows("senate", 1, "status=ungrounded&column=AMOUNT ($)")
    assert amount["matched"] == 61
    plain = app.rows("senate", 1, "column=PAYEE NAME")
    assert plain["matched"] == 124


def test_the_page_filter_keeps_the_rows_of_one_page(app):
    data = app.rows("senate", 1, "page=2")
    assert data["matched"] == 62
    assert {r["page"] for r in data["rows"]} == {2}
    assert app.rows("senate", 1, "page=9")["matched"] == 0


def test_the_flagged_filter_keeps_rows_with_a_cell_that_needs_review(app):
    data = app.rows("senate", 1, "flagged=1")
    assert data["matched"] == 68
    assert all(any(c["status"] not in UNFLAGGED for c in r["cells"]) for r in data["rows"])
    assert app.rows("senate", 1, "flagged=0")["matched"] == 124


def test_the_recheck_filter_keeps_rows_changed_by_the_recheck(app):
    data = app.rows("merged", 0, "recheck=1")
    assert [(r["page"], r["row"]) for r in data["rows"]] == [(5, 3)]
    assert data["rows"][0]["recheck"] is True
    assert app.rows("merged", 0)["matched"] > 1


def test_the_merged_filter_keeps_rows_of_a_merged_part(app):
    data = app.rows("merged", 0, "merged=1")
    assert data["matched"] == sum(
        len(r.rows) for r in app.built.tables["merged"][0].pages if r.page in (4, 5)
    )
    assert {r["page"] for r in data["rows"]} == {4, 5}
    assert all(r["merged"] for r in data["rows"])
    assert not any(r["merged"] for r in app.rows("merged", 0, "page=1")["rows"])


def test_the_ocr_filter_keeps_rows_on_ocr_pages(app):
    edit_run(app.project, app.id["senate"], big=lambda d: d["tables"][1].update(ocr_pages=[2]))
    data = app.rows("senate", 1, "ocr=1")
    assert data["matched"] == 62
    assert {r["page"] for r in data["rows"]} == {2}
    assert all(r["ocr"] for r in data["rows"])
    assert not any(r["ocr"] for r in app.rows("senate", 1, "page=1")["rows"])


def test_the_search_looks_in_every_value_of_a_row_ignoring_case(app):
    rows = app.built.tables["simple_new"][0].rows()

    def expected(text: str) -> int:
        return sum(1 for r in rows if any(text in v.casefold() for v in r.values.values()))

    assert expected("gonzales") >= 2
    assert app.rows("simple_new", 0, "q=gonzales")["matched"] == expected("gonzales")
    assert app.rows("simple_new", 0, "q=GONZALES, tony")["matched"] == expected("gonzales, tony")
    assert app.rows("simple_new", 0, "q=no such text")["matched"] == 0
    assert app.rows("simple_new", 0, "q=17,500")["matched"] == expected("17,500") >= 1


def test_filters_combine(app):
    data = app.rows("senate", 1, "page=2&status=ungrounded&flagged=1&q=")
    expected = sum(
        1
        for r in app.built.tables["senate"][1].page_rows(2)
        if any(c.status == "ungrounded" for c in r.cells.values())
    )
    assert data["matched"] == expected > 0
    nothing = app.rows("senate", 1, "page=1&status=misplaced")
    assert nothing["matched"] == 0
    assert nothing["total"] == 124


def test_review_filters_follow_the_current_verdicts(app):
    rows = [x for x in flagged_rows(app, "senate", 1) if len(x[2]) == 1]
    (a, b, c, d) = rows[:4]
    give(app, "senate", 1, a[0], a[1], a[2][0], "correct")
    give(app, "senate", 1, b[0], b[1], b[2][0], "changed", note="check it")
    give(app, "senate", 1, c[0], c[1], c[2][0], "unsure")
    give(app, "senate", 1, d[0], d[1], d[2][0], "correct", judged="an old value")  # stale

    def hits(review: str) -> set[tuple[int, int]]:
        return {
            (r["page"], r["row"])
            for r in app.rows("senate", 1, f"review={review}&offset=0")["rows"]
        }

    assert hits("correct") == {a[:2]}
    assert hits("changed") == {b[:2]}
    assert hits("unsure") == {c[:2]}
    assert hits("note") == {b[:2]}
    assert hits("any") == {(r["page"], r["row"]) for r in app.rows("senate", 1, "offset=0")["rows"]}
    unreviewed = app.rows("senate", 1, "review=unreviewed")
    assert unreviewed["matched"] == 68 - 3  # the stale verdict does not count
    shown = {(r["page"], r["row"]) for r in unreviewed["rows"]}
    assert d[:2] in shown
    assert not shown & {a[:2], b[:2], c[:2]}


def test_a_draft_note_counts_as_a_note_for_the_filter(app):
    page, row, columns = flagged_rows(app, "senate", 1)[0]
    run = load_run(app.project, app.id["senate"])
    key = CellKey(run.summary.sha256, tuple(run.tables[1].columns), page, row, columns[0])
    DraftStore(app.project).put(key, "look again", None, None)
    assert [(r["page"], r["row"]) for r in app.rows("senate", 1, "review=note")["rows"]] == [
        (page, row)
    ]
    label = app.rows("senate", 1, "review=note")["rows"][0]["review"]
    assert label["note"] is True
    assert label["state"] == "none"


def test_sorting_puts_numbers_in_numeric_order_and_text_in_case_insensitive_order(app):
    ascending = app.rows("simple_new", 0, "sort=Amount")
    amounts = [r["cells"][3]["value"] for r in ascending["rows"]]
    numbers = [float(a.replace("$", "").replace(",", "")) for a in amounts]
    assert numbers == sorted(numbers)
    assert ascending["sort"] == {"column": "Amount", "desc": False}
    descending = app.rows("simple_new", 0, "sort=Amount&desc=1")
    assert [r["cells"][3]["value"] for r in descending["rows"]] == amounts[::-1]
    assert descending["sort"] == {"column": "Amount", "desc": True}
    text = [r["cells"][0]["value"] for r in app.rows("simple_new", 0, "sort=Account")["rows"]]
    assert text == sorted(text, key=str.casefold)


def test_rows_without_a_value_sort_last_in_both_directions(app):
    for direction in ("", "&desc=1"):
        rows = app.rows("senate", 1, f"sort=AMOUNT ($){direction}&offset=0")["rows"]
        values = [r["cells"][6]["value"] for r in rows]
        assert [bool(v) for v in values] == sorted((bool(v) for v in values), reverse=True)


def test_the_default_order_is_page_then_row_and_the_page_and_row_columns_sort(app):
    default = [(r["page"], r["row"]) for r in app.rows("senate", 1)["rows"]]
    assert default == sorted(default)
    by_row = app.rows("senate", 1, "sort=row")["rows"]
    assert [r["row"] for r in by_row] == sorted(r["row"] for r in by_row)
    reverse = app.rows("senate", 1, "sort=page&desc=1")["rows"]
    assert reverse[0]["page"] == 3


def test_a_library_column_whose_name_a_pdf_column_has_gets_a_trailing_underscore(app):
    edit_run(
        app.project,
        app.id["simple_new"],
        big=lambda d: _rename_column(d["tables"][0], "Account", "page"),
    )
    keys = [c["key"] for c in app.rows("simple_new")["columns"]]
    assert keys[:3] == ["page_", "row", "page"]


def _rename_column(table: dict, old: str, new: str) -> None:
    table["columns"] = [new if c == old else c for c in table["columns"]]
    for row in table["rows"]:
        row["values"] = {(new if c == old else c): v for c, v in row["values"].items()}
        row["cells"] = {(new if c == old else c): v for c, v in row["cells"].items()}


def test_extra_fields_are_columns_after_the_values(app):
    data = app.rows("extras")
    assert [(c["key"], c["kind"]) for c in data["columns"]] == [
        ("page", "page"),
        ("row", "row"),
        ("Name", "column"),
        ("Count", "column"),
        ("Share", "column"),
        ("division", "extra"),
    ]
    cell = data["rows"][0]["cells"][-1]
    assert (cell["name"], cell["extra"], cell["value"], cell["status"]) == (
        "division",
        True,
        "Roads",
        "exact",
    )
    assert cell["source_page"] == 1
    carried = next(r for r in data["rows"] if r["page"] == 2)["cells"][-1]
    assert (carried["value"], carried["source_page"]) == ("Roads", 1)


# --- the review column -------------------------------------------------------------------------
def labels(app: App, **query: str) -> dict[tuple[int, int], dict]:
    text = "&".join(f"{k}={v}" for k, v in query.items())
    rows = app.rows("senate", 1, f"offset=0&{text}")["rows"]
    return {(r["page"], r["row"]): r["review"] for r in rows}


def test_a_row_without_a_verdict_is_not_reviewed(app):
    review = labels(app)[(1, 1)]
    assert review == {
        "state": "none",
        "was": None,
        "unreviewed": 1,
        "note": False,
        "ocr": False,
        "merged": False,
        "label": "Not reviewed",
    }


def test_the_label_names_the_most_important_verdict_of_the_row(app):
    two = next((p, r, c) for p, r, c in flagged_rows(app, "senate", 1) if len(c) == 2)
    page, row, (first, second) = two
    other = next(c for c in app.built.tables["senate"][1].columns if c not in (first, second))
    give(app, "senate", 1, page, row, other, "correct")
    assert labels(app)[(page, row)]["label"] == "✓ Correct · 2 not reviewed"
    give(app, "senate", 1, page, row, other, "unsure")
    assert labels(app)[(page, row)]["label"] == "? Can't tell · 2 not reviewed"
    give(app, "senate", 1, page, row, first, "correct")
    give(app, "senate", 1, page, row, other, "changed")
    assert labels(app)[(page, row)]["label"] == "✎ Changed · 1 not reviewed"
    give(app, "senate", 1, page, row, second, "unsure", judged="old amount")
    stale = labels(app)[(page, row)]
    assert stale["state"] == "stale"
    assert stale["was"] == "old amount"
    assert stale["label"] == "Stale · was old amount · 1 not reviewed"


def test_the_label_ends_with_note_ocr_and_merged_part(app):
    page, row, columns = next(
        (p, r, c) for p, r, c in flagged_rows(app, "senate", 1) if len(c) == 1
    )
    give(app, "senate", 1, page, row, columns[0], "correct", note="because")
    edit_run(app.project, app.id["senate"], big=lambda d: d["tables"][1].update(ocr_pages=[page]))
    review = labels(app)[(page, row)]
    assert review["note"] is True
    assert review["ocr"] is True
    assert review["label"] == "✓ Correct · note · OCR page"
    edit_run(
        app.project,
        app.id["senate"],
        big=lambda d: d["tables"][1].update(
            merged=[{"pages": [page], "columns": d["tables"][1]["columns"], "evidence": {}}]
        ),
    )
    assert labels(app)[(page, row)]["label"] == "✓ Correct · note · OCR page · merged part"


def test_an_extra_fields_verdict_shows_on_every_row_that_carries_the_value(app):
    run = load_run(app.project, app.id["extras"])
    VerdictStore(app.project).append(
        Verdict(
            "2026-10-20T12:00:00Z",
            run.summary.id,
            run.summary.name,
            0,
            run.tables[0].label,
            tuple(run.tables[0].columns),
            ExtraKey(run.summary.sha256, "division", 1),
            "Roads",
            "exact",
            "correct",
            None,
            None,
            "",
            {},
        )
    )
    rows = app.rows("extras")["rows"]
    assert {r["page"] for r in rows} == {1, 2, 3}
    assert all(r["review"]["state"] == "correct" for r in rows)
    assert all(r["cells"][-1]["state"] == "correct" for r in rows)


# --- the CSV -----------------------------------------------------------------------------------
def read_csv(body: bytes) -> tuple[list[str], list[list[str]]]:
    rows = list(csv.reader(io.StringIO(body.decode("utf-8"), newline="")))
    return rows[0], rows[1:]


def same_as_records(header: list[str], rows: list[list[str]], table: Table) -> None:
    records = table.records()
    assert header == list(records[0])
    assert len(rows) == len(records)
    for got, expected in zip(rows, records, strict=True):
        for name, text in zip(header, got, strict=True):
            value = expected[name]
            if isinstance(value, float):
                assert float(text) == pytest.approx(value, abs=1e-4), name
            else:
                assert text == ("" if value is None else str(value)), name


@pytest.mark.parametrize(
    ("label", "index"),
    [
        ("simple_new", 0),
        ("senate", 0),
        ("senate", 1),
        ("merged", 0),
        ("extras", 0),
        ("clears", 0),
    ],
)
def test_the_csv_has_the_columns_and_values_of_records(app, label, index):
    status, response, body = app.get(f"{app.run(label)}/tables/{index}/rows.csv")
    assert status == 200
    assert response.getheader("Content-Type") == "text/csv; charset=utf-8"
    header, rows = read_csv(body)
    same_as_records(header, rows, app.built.tables[label][index])


def test_the_csv_names_its_file_after_the_pdf_and_the_table(app):
    _, response, _ = app.get(f"{app.run('senate')}/tables/1/rows.csv")
    stem = SENATE_PDF.stem
    assert response.getheader("Content-Disposition").startswith(
        f'attachment; filename="{stem}-table2.csv"'
    )


def test_the_csv_has_every_matching_row_not_just_a_page(app):
    _, _, body = app.get(f"{app.run('senate')}/tables/1/rows.csv")
    assert len(read_csv(body)[1]) == 124
    _, _, body = app.get(
        f"{app.run('senate')}/tables/1/rows.csv?status=ungrounded&sort=AMOUNT ($)&desc=1"
    )
    header, rows = read_csv(body)
    assert len(rows) == 67
    assert header[0] == "page"


def test_the_csv_header_is_written_even_when_no_row_matches(app):
    _, _, body = app.get(f"{app.run('senate')}/tables/1/rows.csv?page=9")
    header, rows = read_csv(body)
    assert rows == []
    assert header == list(app.built.tables["senate"][1].records()[0])


def test_the_csv_filename_cannot_carry_a_header_injection(app):
    nasty = 'a"b\r\nSet-Cookie: x.pdf'
    edit_run(app.project, app.id["simple_new"], small=lambda d: d["document"].update(name=nasty))
    _, response, _ = app.get(f"{app.run('simple_new')}/tables/0/rows.csv")
    disposition = response.getheader("Content-Disposition")
    assert "\n" not in disposition
    assert response.getheader("Set-Cookie") is None


# --- one cell ----------------------------------------------------------------------------------
def cell_path(  # noqa: PLR0913, PLR0917
    app: App, label: str, table: int, page: int, row: int, column: str, query: str = ""
) -> str:
    base = f"{app.run(label)}/tables/{table}/cells/{page}/{row}/{quote(column, safe='')}"
    return base + (f"?{query}" if query else "")


def extra_path(  # noqa: PLR0913, PLR0917
    app: App, label: str, page: int, row: int, name: str, query: str = ""
) -> str:
    base = f"{app.run(label)}/tables/0/cells/{page}/{row}/extra/{quote(name, safe='')}"
    return base + (f"?{query}" if query else "")


def test_a_cell_has_its_status_value_matched_text_and_numbers(app):
    page, row, columns = flagged_rows(app, "senate", 1)[0]
    data = app.json(cell_path(app, "senate", 1, page, row, columns[0]))
    stored = load_run(app.project, app.id["senate"]).tables[1]
    expected = next(r for r in stored.rows if (r.page, r.row) == (page, row)).cells[columns[0]]
    assert data["kind"] == "cell"
    assert (data["run"], data["table"], data["page"], data["row"]) == (
        app.id["senate"],
        1,
        page,
        row,
    )
    assert (data["name"], data["status"]) == (columns[0], "ungrounded")
    assert "not on the page" in data["explanation"]
    assert (
        data["value"]
        == next(r for r in stored.rows if (r.page, r.row) == (page, row)).values[columns[0]]
    )
    assert data["matched_text"] == expected.matched_text
    assert data["coverage"] == expected.coverage
    assert data["density"] == expected.density
    assert data["places"] == expected.n_candidates


def test_the_whole_row_comes_with_the_cell_and_its_statuses(app):
    page, row, columns = flagged_rows(app, "senate", 1)[0]
    data = app.json(cell_path(app, "senate", 1, page, row, columns[0]))
    assert [c["name"] for c in data["row_cells"]] == app.built.tables["senate"][1].columns
    assert [c["selected"] for c in data["row_cells"]].count(True) == 1
    selected = next(c for c in data["row_cells"] if c["selected"])
    assert (selected["name"], selected["status"]) == (columns[0], "ungrounded")
    assert {c["status"] for c in data["row_cells"]} >= {"empty", "ungrounded"}


def test_every_status_has_an_explanation(app):
    seen = set()
    for label, index in (("senate", 1), ("senate", 0)):
        for r in app.rows(label, index, "offset=0")["rows"]:
            for c in r["cells"]:
                if c["status"] in seen:
                    continue
                seen.add(c["status"])
                data = app.json(cell_path(app, label, index, r["page"], r["row"], c["name"]))
                assert data["explanation"]
    assert seen >= {"exact", "empty", "ungrounded"}


def test_a_cells_highlights_are_the_matched_boxes_areas_band_header_and_page_size(app):
    page, row, columns = (1, 1, ["Account"])
    data = app.json(cell_path(app, "simple_new", 0, page, row, columns[0]))
    stored = load_run(app.project, app.id["simple_new"])
    table, run_row = stored.tables[0], stored.tables[0].rows[0]
    cell = run_row.cells["Account"]
    light = data["highlights"]
    assert light["page"] == 1
    assert light["size"] == stored.pages[1].size
    assert light["matched"] == cell.bbox
    assert light["candidates"] == [b for b in cell.candidates if b != cell.bbox]
    assert light["row_window"] == table.areas[1].rows[1]
    assert light["row_label"] == "row 1"
    assert light["column_range"] == table.areas[1].columns["Account"]
    x0, x1 = table.areas[1].columns["Account"]
    y0, y1 = table.areas[1].rows[1]
    assert light["cell_area"] == [x0, y0, x1, y1]
    assert light["band"] is None
    assert light["header"] == table.layouts[0]["header"]
    assert light["header"]["x"]


def test_other_places_found_are_the_candidates_besides_the_matched_box(app):
    edit_run(
        app.project,
        app.id["simple_new"],
        big=lambda d: d["tables"][0]["rows"][0]["cells"]["Account"].update(
            candidates=[
                [1, 2, 3, 4],
                d["tables"][0]["rows"][0]["cells"]["Account"]["bbox"],
                [5, 6, 7, 8],
            ]
        ),
    )
    light = app.json(cell_path(app, "simple_new", 0, 1, 1, "Account"))["highlights"]
    assert light["candidates"] == [[1, 2, 3, 4], [5, 6, 7, 8]]


def test_a_cell_on_a_shared_page_has_its_tables_band(app):
    data = app.json(cell_path(app, "senate", 0, 1, 1, "DESCRIPTION"))
    stored = load_run(app.project, app.id["senate"]).tables[0]
    assert data["highlights"]["band"] == stored.bands[1]
    other = app.json(cell_path(app, "senate", 1, 1, 1, "PAYEE NAME"))
    assert other["highlights"]["band"] == load_run(app.project, app.id["senate"]).tables[1].bands[1]


def test_a_misplaced_cell_has_its_matched_words_and_its_own_area(app):
    (row,) = app.rows("senate", 1, "page=3&status=misplaced")["rows"]
    column = next(c["name"] for c in row["cells"] if c["status"] == "misplaced")
    data = app.json(cell_path(app, "senate", 1, row["page"], row["row"], column))
    assert data["status"] == "misplaced"
    assert data["highlights"]["matched"] is not None
    assert data["highlights"]["cell_area"] is not None


def test_a_cell_without_stored_areas_has_none(app):
    edit_run(app.project, app.id["simple_new"], big=lambda d: d["tables"][0].update(areas={}))
    light = app.json(cell_path(app, "simple_new", 0, 1, 1, "Account"))["highlights"]
    assert (light["row_window"], light["column_range"], light["cell_area"]) == (None, None, None)


def test_the_cell_knows_its_place_in_the_filter_and_its_neighbours(app):
    rows = flagged_rows(app, "senate", 1)
    cells = [(p, r, c) for p, r, names in rows for c in names]
    assert len(cells) == 75
    p, r, c = cells[10]
    nav = app.json(cell_path(app, "senate", 1, p, r, c, "status=ungrounded,misplaced"))["nav"]
    assert (nav["n"], nav["of"]) == (11, 75)
    ref = lambda t: (t["page"], t["row"], t["name"], t["extra"])  # noqa: E731
    assert ref(nav["previous"]) == (*cells[9], False)
    assert ref(nav["next"]) == (*cells[11], False)
    first = app.json(cell_path(app, "senate", 1, *cells[0], "status=ungrounded,misplaced"))["nav"]
    assert (first["n"], first["previous"]) == (1, None)
    last = app.json(cell_path(app, "senate", 1, *cells[-1], "status=ungrounded,misplaced"))["nav"]
    assert (last["n"], last["next"]) == (75, None)


def test_the_neighbouring_rows_keep_the_column(app):
    rows = flagged_rows(app, "senate", 1)
    nav = app.json(cell_path(app, "senate", 1, rows[5][0], rows[5][1], "AMOUNT ($)", "flagged=1"))[
        "nav"
    ]
    assert (nav["previous_row"]["page"], nav["previous_row"]["row"]) == rows[4][:2]
    assert (nav["next_row"]["page"], nav["next_row"]["row"]) == rows[6][:2]
    assert nav["next_row"]["name"] == "AMOUNT ($)"


def test_a_cell_outside_the_filter_has_no_number_but_still_has_neighbours(app):
    data = app.json(cell_path(app, "senate", 1, 1, 1, "PAYEE NAME", "status=ungrounded"))
    nav = data["nav"]
    assert nav["n"] is None
    assert nav["of"] == 74
    assert nav["previous"] is None
    assert nav["next"] is not None


def test_without_a_filter_every_cell_is_in_the_sequence(app):
    nav = app.json(cell_path(app, "simple_new", 0, 1, 2, "Location"))["nav"]
    assert (nav["n"], nav["of"]) == (7, 11 * 5)
    assert nav["previous"]["name"] == "Account"
    assert nav["next"]["name"] == "Project"


def test_the_filter_for_navigation_follows_the_sort(app):
    rows = app.rows("simple_new", 0, "sort=Amount&desc=1")["rows"]
    second = rows[1]
    nav = app.json(
        cell_path(
            app,
            "simple_new",
            0,
            second["page"],
            second["row"],
            "Amount",
            "sort=Amount&desc=1&column=Amount",
        )
    )["nav"]
    assert nav["n"] == 2
    assert (nav["previous"]["page"], nav["previous"]["row"]) == (rows[0]["page"], rows[0]["row"])
    assert (nav["next"]["page"], nav["next"]["row"]) == (rows[2]["page"], rows[2]["row"])


def test_a_merged_cell_names_its_part_and_original_column(app):
    truth = load_doc("pipe-reworded-gap1")
    names, b_names = truth["parts"][0]["columns"], truth["parts"][1]["columns"]
    data = app.json(cell_path(app, "merged", 0, 4, 1, names[1]))
    assert data["merge"]["pages"] == [4, 5]
    assert data["merge"]["original_column"] == b_names[1]
    assert data["merge"]["columns"] == b_names
    assert set(data["merge"]["evidence"]) >= {
        "token_sets",
        "equal_positions",
        "max_x_difference",
        "shapes",
        "cells",
    }
    assert app.json(cell_path(app, "merged", 0, 1, 1, names[1]))["merge"] is None


def test_a_rechecked_cell_has_its_proposal(app):
    names = load_doc("pipe-reworded-gap1")["parts"][0]["columns"]
    data = app.json(cell_path(app, "merged", 0, 5, 3, names[0]))
    proposal = data["proposal"]
    assert proposal["outcome"] == "accepted"
    assert proposal["original"].endswith("Zzyzx")
    assert proposal["proposed"] == data["value"]
    assert proposal["status_before"] != "exact"
    assert proposal["status_after"] == "exact"
    assert app.json(cell_path(app, "merged", 0, 5, 2, names[0]))["proposal"] is None


def test_a_cell_on_an_ocr_page_says_so(app):
    edit_run(app.project, app.id["senate"], big=lambda d: d["tables"][1].update(ocr_pages=[2]))
    assert app.json(cell_path(app, "senate", 1, 2, 1, "PAYEE NAME"))["ocr"] is True
    assert app.json(cell_path(app, "senate", 1, 1, 1, "PAYEE NAME"))["ocr"] is False


def test_an_extra_field_has_the_page_that_prints_it_and_whether_it_was_carried(app):
    own = app.json(extra_path(app, "extras", 1, 1, "division"))
    carried = app.json(extra_path(app, "extras", 2, 1, "division"))
    assert own["kind"] == "extra"
    assert (own["name"], own["value"], own["status"]) == ("division", "Roads", "exact")
    assert own["extra"] == {"name": "division", "source_page": 1, "carried": False, "change": None}
    assert carried["extra"]["source_page"] == 1
    assert carried["extra"]["carried"] is True
    assert carried["highlights"]["page"] == 1  # the page that prints it
    assert carried["highlights"]["matched"] is not None
    assert carried["highlights"]["row_window"] is None
    assert [c["name"] for c in carried["row_cells"]] == ["Name", "Count", "Share", "division"]
    assert [c["selected"] for c in carried["row_cells"]] == [False, False, False, True]
    assert carried["row_cells"][-1]["extra"] is True


def test_an_extra_field_with_an_accepted_recheck_shows_the_change(app):
    edit_run(
        app.project,
        app.id["extras"],
        big=lambda d: d["tables"][0].update(extra_changes=[[1, "division", "Rods", "Roads"]]),
    )
    data = app.json(extra_path(app, "extras", 1, 1, "division"))
    assert data["extra"]["change"] == {"original": "Rods", "new": "Roads"}
    assert app.rows("extras", 0, "recheck=1")["matched"] == 12


def test_an_extra_field_nothing_printed_has_no_page_and_cannot_be_reviewed(app):
    data = app.json(extra_path(app, "clears", 4, 1, "division"))
    assert (data["value"], data["status"]) == ("", "empty")
    assert data["extra"]["source_page"] is None
    assert data["review"]["reviewable"] is False
    assert data["review"]["key"] is None
    assert data["highlights"]["matched"] is None


def test_a_cell_shows_its_verdict_draft_and_key(app):
    page, row, columns = flagged_rows(app, "senate", 1)[0]
    column = columns[0]
    untouched = app.json(cell_path(app, "senate", 1, page, row, column))["review"]
    run = load_run(app.project, app.id["senate"])
    key = CellKey(run.summary.sha256, tuple(run.tables[1].columns), page, row, column)
    assert untouched == {
        "state": "none",
        "verdict": None,
        "draft": None,
        "reviewable": True,
        "key": key.to_json(),
    }
    give(app, "senate", 1, page, row, column, "changed", note="typo")
    DraftStore(app.project).put(key, "half typed", "x", "spacing")
    review = app.json(cell_path(app, "senate", 1, page, row, column))["review"]
    assert review["state"] == "changed"
    assert review["verdict"]["verdict"] == "changed"
    assert review["verdict"]["note"] == "typo"
    assert review["verdict"]["value"] == "other"
    assert review["verdict"]["time"] == "2026-10-20T12:00:00Z"
    saved = DraftStore(app.project).get(key)
    assert saved is not None
    assert review["draft"] == {
        "note": "half typed",
        "value": "x",
        "category": "spacing",
        "saved_at": saved.saved_at,
    }


def test_a_stale_verdict_is_shown_with_the_value_it_judged(app):
    page, row, columns = flagged_rows(app, "senate", 1)[0]
    give(app, "senate", 1, page, row, columns[0], "correct", judged="old value")
    review = app.json(cell_path(app, "senate", 1, page, row, columns[0]))["review"]
    assert review["state"] == "stale"
    assert review["verdict"]["extracted"] == "old value"


@pytest.mark.parametrize(
    "suffix",
    [
        "9/1/PAYEE NAME",  # no such page
        "1/999/PAYEE NAME",  # no such row
        "1/1/NOT A COLUMN",
        "1/1/extra/division",  # this table has no extra fields
        "1/1/..%2f..%2fx",
        "1/1/%2e%2e",
        "../1/1/PAYEE NAME",
        "1/1/PAYEE NAME/more",
    ],
)
def test_an_unknown_page_row_column_or_extra_field_is_404(app, suffix):
    assert app.error(f"{app.run('senate')}/tables/1/cells/{suffix}")


def test_an_unknown_table_is_404(app):
    assert app.error(f"{app.run('senate')}/tables/2/rows")
    assert app.error(f"{app.run('senate')}/tables/2/rows.csv")
    assert app.error(f"{app.run('senate')}/tables/2/cells/1/1/PAYEE NAME")
    assert app.error(f"{app.run('senate')}/tables/x/rows")


# --- pages and the PDF -------------------------------------------------------------------------
def test_a_page_has_its_size_words_and_the_tables_on_it(app):
    data = app.json(f"{app.run('senate')}/pages/1")
    stored = load_run(app.project, app.id["senate"])
    assert data["page"] == 1
    assert data["size"] == stored.pages[1].size
    assert data["words"] == stored.pages[1].words
    assert data["ocr"] is False
    assert [t["index"] for t in data["tables"]] == [0, 1]
    assert [t["band"] for t in data["tables"]] == [
        stored.tables[0].bands[1],
        stored.tables[1].bands[1],
    ]
    assert data["tables"][0]["header"] == stored.tables[0].layouts[0]["header"]
    only = app.json(f"{app.run('senate')}/pages/2")
    assert [(t["index"], t["band"]) for t in only["tables"]] == [(1, None)]


@pytest.mark.parametrize("page", ["0", "4", "99", "x", "-1", "1.5"])
def test_a_page_the_run_does_not_hold_is_404(app, page):
    assert app.error(f"{app.run('senate')}/pages/{page}")
    assert app.error(f"{app.run('senate')}/pages/{page}.png")


def test_a_page_of_the_document_without_a_table_has_an_image_but_no_words(app):
    run = app.run("merged")
    assert app.json(f"{run}/pages/1")["words"]
    status, _, _ = app.get(f"{run}/pages/3")
    assert status == 404  # no table on it, so no text was stored
    assert app.get(f"{run}/pages/3.png")[0] == 200


def test_a_page_image_is_a_png_of_the_pdf_page(app):
    status, response, body = app.get(f"{app.run('senate')}/pages/2.png")
    assert status == 200
    assert response.getheader("Content-Type") == "image/png"
    assert body.startswith(b"\x89PNG\r\n\x1a\n")
    assert response.getheader("Content-Security-Policy")
    with pymupdf.open(SENATE_PDF) as document:
        expected = document[1].get_pixmap(dpi=150)
    assert pymupdf.Pixmap(body).width == expected.width


def test_rendered_pages_are_cached_by_document_and_page(app, monkeypatch):
    sources.clear_caches()
    real = extract.render_png
    calls = []

    def counting(page):
        calls.append(page.number)
        return real(page)

    monkeypatch.setattr(extract, "render_png", counting)
    for _ in range(3):
        assert app.get(f"{app.run('senate')}/pages/1.png")[0] == 200
    assert app.get(f"{app.run('senate')}/pages/2.png")[0] == 200
    assert calls == [0, 1]


def test_two_runs_of_one_document_share_the_cached_pages(app, monkeypatch):
    sources.clear_caches()
    real = extract.render_png
    calls = []
    monkeypatch.setattr(extract, "render_png", lambda page: (calls.append(1), real(page))[1])
    assert app.get(f"{app.run('simple_old')}/pages/1.png")[0] == 200
    assert app.get(f"{app.run('simple_new')}/pages/1.png")[0] == 200
    assert calls == [1]


def test_the_pdf_is_served_whole_when_it_matches(app):
    status, response, body = app.get(f"{app.run('senate')}/pdf")
    assert status == 200
    assert response.getheader("Content-Type") == "application/pdf"
    assert response.getheader("Content-Disposition").startswith("inline")
    assert body == SENATE_PDF.read_bytes()


# --- the whole API -----------------------------------------------------------------------------
def test_browsing_writes_nothing_to_the_project_folder(app):
    paths = [
        "/api/runs",
        "/api/runs?document=a&model=b",
    ]
    for label, run_id in app.id.items():
        base = f"/api/runs/{run_id}"
        paths += [base, f"{base}/pdf", f"{base}/pages/1", f"{base}/pages/1.png"]
        for index in range(len(app.built.tables[label])):
            paths += [
                f"{base}/tables/{index}/rows",
                f"{base}/tables/{index}/rows?review=note&status=exact",
                f"{base}/tables/{index}/rows.csv",
            ]
    before = snapshot(app.project)
    for path in paths:
        assert app.get(path)[0] in (200, 404), path
    assert app.json(f"/api/runs/{app.id['senate']}/tables/1/cells/1/1/PAYEE NAME")
    assert snapshot(app.project) == before


def test_every_response_carries_the_security_headers_and_json_is_not_cached(app):
    _, response, _ = app.get("/api/runs")
    assert response.getheader("Cache-Control") == "no-store"
    assert response.getheader("Content-Security-Policy")
    _, response, _ = app.get(f"{app.run('senate')}/tables/1/rows.csv")
    assert response.getheader("X-Content-Type-Options") == "nosniff"
