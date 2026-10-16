"""The OCR'd Senate report: a summary table above the detail table on page 1, replayed offline."""

import json

from quotable.models import PageRows, WindowTables
from tests.conftest import DATA, FakeClient, extract_tables

PDF = DATA / "senate_expenditures_paddleocr.pdf"
RECORDED = json.loads((DATA / "senate_expenditures_paddleocr.rows.json").read_text())


def recorded_model() -> FakeClient:
    discovery = WindowTables.model_validate(RECORDED["discovery"])
    first_columns = {t.label: t.columns[0].name for p in discovery.pages for t in p.tables}
    rows = {
        (first_columns[t["label"]], int(page)): r
        for t in RECORDED["tables"]
        for page, r in t["pages"].items()
    }

    def handler(request):
        if request.stage == "schema":
            return discovery
        first_column = request.parts[0].splitlines()[1].split(":")[0].removeprefix("- ")
        return PageRows(rows=[dict(r) for r in rows[first_column, request.page]])

    return FakeClient(handler)


def test_both_tables_come_back_with_their_own_pages_and_rows():
    client = recorded_model()
    summary, detail = extract_tables(PDF, client, recheck=False)
    assert client.stages() == ["schema"] + ["extract"] * 4  # three pages fit in one window
    assert (summary.label, detail.label) == ("Expenditure summary", "Expenditure detail")
    assert len(summary.columns) == 4 and len(detail.columns) == 7
    assert {r.page: len(r.rows) for r in summary.pages} == {1: 7}
    assert {r.page: len(r.rows) for r in detail.pages} == {1: 36, 2: 62, 3: 26}


def test_page_one_is_split_into_the_two_tables_bands():
    summary, detail = extract_tables(PDF, recorded_model(), recheck=False)
    assert len(summary.layers[1].words) == 34
    assert len(detail.layers[1].words) == 279
    assert len(detail.layers[2].words) == 479  # pages with one table keep the whole page


def test_the_summary_table_is_grounded_in_its_own_band():
    summary, _ = extract_tables(PDF, recorded_model(), recheck=False)
    assert summary.position["misplaced"] == 0
    statuses = [c.status for row in summary.rows() for c in row.cells.values()]
    assert statuses.count("exact") == 17 and statuses.count("empty") == 11
    assert summary.page_rows(1)[0].values["DESCRIPTION"] == "Authorization"
