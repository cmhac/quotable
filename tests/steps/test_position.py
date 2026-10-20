import copy
import hashlib
import json
from pathlib import Path

import pymupdf
import pytest

from quotable.steps.grounding import ground_rows
from quotable.steps.position import PageGrounding, check_positions
from quotable.text.layer import load_layer
from tests.fixture_tables import doc_ids, tables_of

IDS = doc_ids()


def _ground_document(pdf, columns, pages):
    """Ground ``pages`` ({page number: rows}) the way the pipeline does."""
    out = []
    with pymupdf.open(pdf) as document:
        for number, rows in sorted(pages.items()):
            layer = load_layer(document[number - 1])
            out.append(PageGrounding(rows, ground_rows(rows, columns, layer), layer))
    return out


def _statuses(page, column):
    return [cells[column].status for cells in page.cells]


def test_a_correct_extraction_has_no_misplaced_cells(sample):
    grounded = _ground_document(sample["pdf"], sample["columns"], sample["pages"])
    counts = check_positions(sample["columns"], grounded)
    # The ag sample has a couple of cells the model really did misplace.
    assert counts["misplaced"] <= (2 if sample["name"] == "fy22_ag_house_original" else 0)


def test_a_project_moved_to_another_row_still_grounds_but_is_misplaced(sample):
    columns = sample["columns"]
    column = next(c for c in columns if c.startswith("Project"))
    pages = copy.deepcopy(sample["pages"])
    rows = pages[1]
    baseline = _statuses(_ground_document(sample["pdf"], columns, sample["pages"])[0], column)
    exact_rows = [i for i, s in enumerate(baseline) if s == "exact"]
    a, b = exact_rows[1], exact_rows[-2]  # two rows far apart
    assert rows[a][column] != rows[b][column]
    rows[a][column], rows[b][column] = rows[b][column], rows[a][column]

    grounded = _ground_document(sample["pdf"], columns, pages)
    assert _statuses(grounded[0], column)[a] == "exact"  # page-wide grounding is fooled
    assert _statuses(grounded[0], column)[b] == "exact"

    check_positions(columns, grounded)
    assert _statuses(grounded[0], column)[a] == "misplaced"
    assert _statuses(grounded[0], column)[b] == "misplaced"


def test_a_value_in_the_wrong_column_is_misplaced(sample):
    columns = sample["columns"]
    amount, project = (
        (next(c for c in columns if c.startswith(p)) for p in ("Amount", "Project"))
        if not sample["name"].startswith("fy24")
        else ("House Amount", "Project")
    )
    pages = copy.deepcopy(sample["pages"])
    row = pages[1][2]
    row[project] = row[amount]  # the amount now sits under Project

    grounded = _ground_document(sample["pdf"], columns, pages)
    assert _statuses(grounded[0], project)[2] == "exact"
    check_positions(columns, grounded)
    assert _statuses(grounded[0], project)[2] == "misplaced"


def test_a_value_shared_by_consecutive_rows_is_not_misplaced(sample):
    # Merged cells print once and are repeated by the model in every row they cover.
    columns = sample["columns"]
    pages = sample["pages"]
    grounded = _ground_document(sample["pdf"], columns, pages)
    check_positions(columns, grounded)
    for page_rows, page in zip(pages.values(), grounded, strict=True):
        for i in range(1, len(page_rows)):
            for column in columns:
                value = page_rows[i][column]
                if value and value == page_rows[i - 1][column]:
                    assert page.cells[i][column].status != "misplaced"


def test_cells_that_cannot_be_judged_are_counted_not_flagged(make_pdf):
    # One row, one column of evidence: no column band can be fitted.
    path = make_pdf([[(72, 100, "Alpha"), (200, 100, "Beta")]])
    pages = {1: [{"A": "Alpha", "B": "Beta"}]}
    grounded = _ground_document(path, ["A", "B"], pages)
    counts = check_positions(["A", "B"], grounded)
    assert counts["unchecked"] == 2
    assert counts["misplaced"] == 0


BASELINE = Path(__file__).parent / "position_baseline.json"


def _outcome(doc_id):
    """Position counts and a digest of every cell's status, per part of a fixture document."""
    out = {}
    for part_id, table in sorted(tables_of(doc_id).items()):
        statuses = [
            f"{page}:{i}:{c}:{g.status}"
            for page, grounded in sorted(table.grounded.items())
            for i, cells in enumerate(grounded.cells)
            for c, g in cells.items()
        ]
        digest = hashlib.sha1("\n".join(statuses).encode()).hexdigest()
        out[part_id] = {"position": table.position, "statuses": digest}
    return out


@pytest.mark.parametrize("doc_id", IDS)
def test_every_row_with_an_anchor_has_a_window_and_every_banded_column_a_range(doc_id):
    for table in tables_of(doc_id).values():
        for grounded in table.grounded.values():
            assert set(grounded.row_windows) <= set(range(len(grounded.rows)))
            for low, high in grounded.row_windows.values():
                assert low < high
            for low, high in grounded.column_ranges.values():
                assert low < high
            assert set(grounded.column_ranges) <= set(table.columns)


def test_a_page_with_evidence_has_windows_for_all_rows_and_ranges_for_banded_columns():
    table = tables_of("struct-shared-page")["A"]
    for grounded in table.grounded.values():
        assert sorted(grounded.row_windows) == list(range(len(grounded.rows)))
    assert any(g.column_ranges for g in table.grounded.values())


def test_a_page_without_evidence_has_no_ranges(make_pdf):
    path = make_pdf([[(72, 100, "Alpha"), (200, 100, "Beta")]])
    grounded = _ground_document(path, ["A", "B"], {1: [{"A": "Alpha", "B": "Beta"}]})
    check_positions(["A", "B"], grounded)
    assert grounded[0].column_ranges == {}


def test_the_windows_of_a_page_are_the_fitted_ones(sample):
    grounded = _ground_document(sample["pdf"], sample["columns"], sample["pages"])
    check_positions(sample["columns"], grounded)
    for page in grounded:
        assert page.row_windows
        ordered = [page.row_windows[i] for i in sorted(page.row_windows)]
        assert all(a[0] <= b[0] for a, b in zip(ordered, ordered[1:], strict=False))
        assert page.column_ranges
        assert set(page.column_ranges) <= set(sample["columns"])
        for low, high in page.column_ranges.values():
            assert low < high


def test_a_page_not_yet_checked_has_no_areas(sample):
    (page, *_) = _ground_document(sample["pdf"], sample["columns"], sample["pages"])
    assert page.row_windows == {}
    assert page.column_ranges == {}


@pytest.mark.parametrize("doc_id", IDS)
def test_statuses_and_counts_of_the_fixture_are_unchanged(doc_id):
    baseline = json.loads(BASELINE.read_text())
    assert _outcome(doc_id) == baseline[doc_id]
