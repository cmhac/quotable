"""Several tables, in any order and under any names (spec 016 task 025, SC-003)."""

import itertools
import json

import pytest

from quotable.gold.score import ExtractedTable, RunRef, TableRows, evaluate, score_page
from quotable.gold.store import GoldPage, GoldTable, Sample, SampleDoc, key
from tests.fixture_tables import DATA

SHA = "a" * 64
REF = RunRef("r" * 32, "2026-11-10T00:00:00Z", "fake", "doc.pdf")


def shared_page_parts():
    truth = json.loads((DATA / "struct-shared-page.json").read_text())
    return truth["parts"]


def gold_tables(parts, page, *, order, rename):
    tables = []
    for n in order:
        part = parts[n]
        columns = [f"col{i}" for i in range(len(part["columns"]))] if rename else part["columns"]
        tables.append(GoldTable(list(columns), [list(r) for r in part["rows"][str(page)]]))
    return tables


def extracted(parts, page):
    return [
        TableRows(
            n, f"Table {n + 1}", list(part["columns"]), [list(r) for r in part["rows"][str(page)]]
        )
        for n, part in enumerate(parts)
    ]


@pytest.mark.parametrize(
    ("order", "rename"), list(itertools.product([(0, 1), (1, 0)], [False, True]))
)
def test_two_tables_on_a_shared_page_score_100_percent_in_any_order_and_under_any_names(
    order, rename
):
    parts = shared_page_parts()
    for page in (1, 2):
        golds = gold_tables(parts, page, order=order, rename=rename)
        page_score = score_page(SHA, page, golds, extracted(parts, page))
        assert page_score.correct, (order, rename, page)
        assert page_score.unmatched_gold == page_score.unmatched_extracted == []
        assert page_score.counts.cells_correct == page_score.counts.cells
        assert len(page_score.pairs) == 2
        # each gold table is paired with the extracted table of the same rows
        assert sorted(p.extracted for p in page_score.pairs) == [0, 1]
        for pair in page_score.pairs:
            assert pair.gold - 1 == order.index(pair.extracted)


def test_the_scores_of_all_four_combinations_are_identical():
    parts = shared_page_parts()
    seen = set()
    for order, rename in itertools.product([(0, 1), (1, 0)], [False, True]):
        counts = []
        for page in (1, 2):
            c = score_page(
                SHA,
                page,
                gold_tables(parts, page, order=order, rename=rename),
                extracted(parts, page),
            ).counts
            counts.append(
                (c.cells, c.cells_correct, c.gold_rows, c.pred_rows, c.rows_correct, c.rows)
            )
        seen.add(tuple(counts))
    assert len(seen) == 1


def test_renamed_columns_are_reported_as_paired_by_values():
    parts = shared_page_parts()
    page_score = score_page(
        SHA, 1, gold_tables(parts, 1, order=(0, 1), rename=True), extracted(parts, 1)
    )
    hows = {c.how for pair in page_score.pairs for c in pair.columns}
    assert hows == {"values"}


def test_a_sample_of_pages_5_and_8_scores_only_those_pages_of_a_long_table():
    columns = ["Name", "Amount"]
    pages = {p: [[f"row {p}-{i}", str(p * 10 + i)] for i in range(3)] for p in range(4, 10)}
    sample = Sample(
        1, 2, "2026-11-10T00:00:00Z", [SampleDoc(SHA, "doc.pdf", 12)], [(SHA, 5), (SHA, 8)]
    )
    gold = {
        key(SHA, p): GoldPage(SHA, p, [GoldTable(columns, pages[p])], True, 1.0, "z")
        for p in (5, 8)
    }
    report = evaluate(sample, gold, {SHA: (REF, [ExtractedTable(0, "Table 1", columns, pages)])})
    assert [p.page for p in report.pages] == [5, 8]
    assert report.total.gold_rows == report.total.pred_rows == 6
    assert report.units[2].correct == 2


def test_a_continuation_page_is_scored_with_the_column_names_as_typed_there():
    extracted_table = TableRows(0, "Table 1", ["Recipient", "Amount"], [["Ann", "1"], ["Bob", "2"]])
    golds = [GoldTable(["Name", "Money"], [["Ann", "1"], ["Bob", "2"]])]
    page_score = score_page(SHA, 6, golds, [extracted_table])
    assert page_score.correct
