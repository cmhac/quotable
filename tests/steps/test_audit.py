"""`audit_table` with a recording fake client (spec 014)."""

import asyncio
from dataclasses import replace
from pathlib import Path

import pytest

from quotable.llm.answers import FilledCell, MissingRow, Omissions
from quotable.llm.client import Image
from quotable.llm.images import TODAY
from quotable.steps.audit import audit_table
from quotable.table import Table, ground_document
from tests.conftest import FakeClient
from tests.table_builder import build_table

COLUMNS = ["Item", "Amount"]
XS = [50.0, 250.0]
PAGES = 6  # enough for the repeated header to count as page furniture


def rows_of(page: int, count: int = 4) -> list[dict[str, str]]:
    return [{"Item": f"Proj{page}x{r}", "Amount": f"${page}{r}00"} for r in range(1, count + 1)]


def complete(tmp_path: Path) -> Table:
    """Six pages of four rows, every row extracted."""
    return build_table(tmp_path, COLUMNS, [rows_of(p) for p in range(1, PAGES + 1)], xs=XS)


def without(table: Table, page: int, row: int, *, blank: str | None = None) -> Table:
    """The table as a model that dropped a row (or blanked a cell of it) would have returned it."""
    pages = []
    for result in table.pages:
        if result.page != page:
            pages.append(result)
        elif blank is None:
            pages.append(
                replace(result, rows=[r for i, r in enumerate(result.rows, 1) if i != row])
            )
        else:
            rows = [dict(r) for r in result.rows]
            rows[row - 1][blank] = ""
            pages.append(replace(result, rows=rows))
    grounded, position = ground_document(table.columns, pages, table.layers)
    return replace(table, pages=pages, grounded=grounded, position=position)


def run(table: Table, tmp_path: Path, client: FakeClient) -> Table:
    gate = asyncio.Semaphore(4)
    return asyncio.run(audit_table(table, tmp_path / "t.pdf", client, TODAY, gate))


def answer(found: Omissions):
    return FakeClient(lambda request: found)


NOTHING = Omissions(missing_rows=[], filled_cells=[])


def test_a_table_whose_every_word_is_explained_makes_no_request(tmp_path):
    client = answer(NOTHING)
    table = complete(tmp_path)
    assert run(table, tmp_path, client) is table
    assert client.requests == []


def test_only_the_page_with_unexplained_words_is_asked_and_once(tmp_path):
    client = answer(NOTHING)
    run(without(complete(tmp_path), 2, 3), tmp_path, client)
    assert [(r.stage, r.page) for r in client.requests] == [("audit", 2)]
    text = "\n".join(p for p in client.requests[0].parts if isinstance(p, str))
    assert "Proj2x3" in text and "Row 1:" in text
    assert sum(isinstance(p, Image) for p in client.requests[0].parts) == 1


def test_a_dropped_row_comes_back_in_page_order_marked_and_grounded(tmp_path):
    dropped = rows_of(2)[2]
    found = Omissions(missing_rows=[MissingRow(after_row=2, values=dropped)], filled_cells=[])
    table = run(without(complete(tmp_path), 2, 3), tmp_path, answer(found))
    assert [r.values for r in table.page_rows(2)] == rows_of(2)
    assert table.page_rows(2)[2].status == "exact"
    assert [(a.page, a.kind, a.outcome, a.row) for a in table.audit] == [(2, "row", "accepted", 3)]
    marks = [r["audit_added"] for r in table.records() if r["page"] == 2]
    assert marks == ["", "", "row", ""]
    assert {r["audit_added"] for r in table.records() if r["page"] != 2} == {""}


def test_a_blank_cell_the_page_prints_is_named_and_filled(tmp_path):
    cut = without(complete(tmp_path), 3, 2, blank="Amount")
    client = answer(
        Omissions(missing_rows=[], filled_cells=[FilledCell(row=2, column="Amount", value="$3200")])
    )
    table = run(cut, tmp_path, client)
    text = "\n".join(p for p in client.requests[0].parts if isinstance(p, str))
    assert "Row 2, Amount: $3200" in text  # the empty cell whose area prints a word
    assert table.page_rows(3)[1].values["Amount"] == "$3200"
    assert [r["audit_added"] for r in table.records() if r["page"] == 3] == [
        "",
        "cells: Amount",
        "",
        "",
    ]


def test_proposals_the_text_layer_does_not_confirm_change_nothing_but_are_recorded(tmp_path):
    invented = {"Item": "Proj2x9", "Amount": "$9999"}
    found = Omissions(missing_rows=[MissingRow(after_row=2, values=invented)], filled_cells=[])
    cut = without(complete(tmp_path), 2, 3)
    table = run(cut, tmp_path, answer(found))
    assert [r.values for r in table.page_rows(2)] == [
        r for i, r in enumerate(rows_of(2), 1) if i != 3
    ]
    assert [(a.kind, a.outcome, a.row) for a in table.audit] == [("row", "ungrounded", None)]
    assert table.pages == cut.pages  # no re-grounding was needed
    assert {r["audit_added"] for r in table.records()} == {""}


def test_a_cell_of_only_dots_or_dashes_stays_as_extracted_and_is_not_an_omission(tmp_path):
    pages = [rows_of(p) for p in range(1, PAGES + 1)]
    pages[1][0]["Amount"] = "....."
    pages[1][1]["Amount"] = "---"
    table = build_table(tmp_path, COLUMNS, pages, xs=XS)
    client = answer(NOTHING)
    assert run(table, tmp_path, client) is table
    assert client.requests == []
    assert [r.values["Amount"] for r in table.page_rows(2)][:2] == [".....", "---"]


def test_a_word_outside_a_shared_pages_band_is_not_counted(tmp_path):
    full = without(complete(tmp_path), 2, 3)
    whole = full.layers[2]
    # a table that shares the page owns only its band: here, the lines above the dropped row
    top = min(w.bbox[1] for w in whole.words if w.text == "Proj2x3")
    narrow = replace(full, layers={**full.layers, 2: whole.crop(0, top - 2, -1e9, 1e9)})
    banded = answer(NOTHING)
    run(narrow, tmp_path, banded)
    assert banded.requests == []
    whole_page = answer(NOTHING)
    run(full, tmp_path, whole_page)
    assert [r.page for r in whole_page.requests] == [2]


def test_a_request_that_fails_makes_the_audit_raise_the_same_error(tmp_path):
    def fail(request):
        raise ConnectionError("provider down")

    with pytest.raises(ConnectionError, match="provider down"):
        run(without(complete(tmp_path), 2, 3), tmp_path, FakeClient(fail))


def test_an_answer_whose_proposals_are_all_rejected_is_not_an_error(tmp_path):
    found = Omissions(
        missing_rows=[MissingRow(after_row=9, values={"Item": "Proj2x3", "Amount": "$2300"})],
        filled_cells=[FilledCell(row=0, column="Amount", value="$2300")],
    )
    table = run(without(complete(tmp_path), 2, 3), tmp_path, answer(found))
    assert sorted(a.outcome for a in table.audit) == ["invalid_cell", "invalid_row"]


def wide_table(tmp_path: Path) -> Table:
    """Six pages of four rows whose Item has four words, so one wrong word is a partial match."""
    pages = [
        [{"Item": f"Road Bridge Culvert Proj{p}x{r}", "Amount": f"${p}{r}00"} for r in range(1, 5)]
        for p in range(1, PAGES + 1)
    ]
    return build_table(tmp_path, COLUMNS, pages, xs=XS)


def test_a_partly_matched_row_is_added_flagged_fuzzy_and_left_to_the_recheck(tmp_path):
    partly = {"Item": "Road Bridge Zzyzx Proj2x3", "Amount": "$2300"}  # one word not on the page
    found = Omissions(missing_rows=[MissingRow(after_row=2, values=partly)], filled_cells=[])
    table = run(without(wide_table(tmp_path), 2, 3), tmp_path, answer(found))
    row = table.page_rows(2)[2]
    assert row.values == partly  # the model's spelling is kept
    assert row.cells["Item"].status == "fuzzy"
    assert [(f.page, f.row, f.column, f.status) for f in table.flagged()] == [
        (2, 3, "Item", "fuzzy")
    ]
    assert [(a.outcome, a.row) for a in table.audit] == [("accepted", 3)]
    assert [r["audit_added"] for r in table.records() if r["page"] == 2][2] == "row"


def test_a_row_with_a_value_that_matches_nothing_is_still_refused(tmp_path):
    nothing = {"Item": "Qqq Zzyzx Www Vvv", "Amount": "$2300"}
    found = Omissions(missing_rows=[MissingRow(after_row=2, values=nothing)], filled_cells=[])
    table = run(without(wide_table(tmp_path), 2, 3), tmp_path, answer(found))
    assert [a.outcome for a in table.audit] == ["ungrounded"]
    assert len(table.page_rows(2)) == 3
