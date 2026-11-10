"""Scoring a whole sample (spec 015 tasks 010 and 015): the headline units, faults, the interval."""

import copy
import json

import pytest

from quotable.gold.score import (
    ExtractedTable,
    RunRef,
    TableRows,
    evaluate,
    progress,
)
from quotable.gold.store import GoldError, GoldPage, GoldTable, Sample, SampleDoc, key
from tests.fixture_tables import DATA

SHA = "a" * 64
OTHER = "b" * 64
REF = RunRef("r" * 32, "2026-11-10T00:00:00Z", "fake", "doc.pdf")


def page_record(sha, page, tables, *, done=True) -> GoldPage:
    return GoldPage(sha, page, tables, done, 1.0, "2026-11-10T00:00:00Z")


def truth_part():
    """The first single-part fixture document with at least two pages."""
    for entry in json.loads((DATA / "manifest.json").read_text()):
        truth = json.loads((DATA / f"{entry['id']}.json").read_text())
        if len(truth["parts"]) == 1 and len(truth["parts"][0]["pages"]) >= 2:
            return truth["parts"][0]
    raise AssertionError("no fixture document")


def build(pages_total=None, extracted_rows=None):
    part = truth_part()
    pages = [int(p) for p in part["pages"]]
    columns = list(part["columns"])
    rows = {p: [list(r) for r in part["rows"][str(p)]] for p in pages}
    sample = Sample(
        1,
        len(pages),
        "2026-11-10T00:00:00Z",
        [SampleDoc(SHA, "doc.pdf", pages_total or len(pages))],
        [(SHA, p) for p in pages],
    )
    gold = {key(SHA, p): page_record(SHA, p, [GoldTable(columns, rows[p])]) for p in pages}
    pred_rows = extracted_rows if extracted_rows is not None else copy.deepcopy(rows)
    table = ExtractedTable(0, "Table 1", columns, pred_rows)
    return sample, gold, {SHA: (REF, [table])}, pages, columns, rows


def filled(row) -> int:
    return sum(1 for v in row if v.strip())


def test_a_perfect_extraction_scores_100_percent_everywhere():
    sample, gold, extracted, *_ = build()
    report = evaluate(sample, gold, extracted)
    for unit in report.units:
        assert (unit.recall, unit.precision, unit.accuracy) == (1.0, 1.0, 1.0)
    assert report.cells == []
    assert report.total.missed == report.total.extra == 0
    assert report.not_scored == []


def test_injected_faults_come_back_as_exactly_those_counts():
    """SC-002: 3 wrong cells, 1 dropped row and 1 extra row on fixture truth."""
    sample, gold, _, pages, columns, rows = build()
    pred = copy.deepcopy(rows)
    first, second = pages[0], pages[1]
    assert len(pred[first]) >= 5
    wrong = [(first, 0, 0), (first, 1, 1), (second, 0, 0)]
    for page, r, c in wrong:
        assert pred[page][r][c].strip()
        pred[page][r][c] = "#### " + pred[page][r][c]
    dropped = pred[first].pop(3)
    pred[second].append(["@@@@ extra"] + ["%%%%"] * (len(columns) - 1))
    extracted = {SHA: (REF, [ExtractedTable(0, "Table 1", columns, pred)])}
    report = evaluate(sample, gold, extracted)

    gold_cells = sum(filled(r) for p in pages for r in rows[p])
    gold_rows = sum(len(rows[p]) for p in pages)
    total = report.total
    assert total.missed == filled(dropped)
    assert total.extra == len(columns)
    assert total.cells_correct == gold_cells - filled(dropped) - 3
    assert (total.gold_rows, total.pred_rows) == (gold_rows, gold_rows)
    assert (total.matched_rows, total.rows, total.rows_correct) == (
        gold_rows - 1,
        gold_rows + 1,
        gold_rows - 1 - 3,
    )
    wrong_pages = {first, second}
    assert [p.page for p in report.pages if not p.correct] == sorted(wrong_pages)
    assert report.units[2].correct == len(pages) - len(wrong_pages)
    assert len(report.cells) == 3 + filled(dropped) + len(columns)


def test_a_difference_of_formatting_only_is_not_an_error_but_is_listed():
    sample, gold, _, pages, columns, rows = build()
    pred = copy.deepcopy(rows)
    pred[pages[0]][0][0] = pred[pages[0]][0][0].upper() + " "
    report = evaluate(sample, gold, {SHA: (REF, [ExtractedTable(0, "T", columns, pred)])})
    assert report.units[0].recall == 1.0
    [cell] = report.cells
    assert cell["best"] == "normal"
    assert (cell["document"], cell["page"], cell["table"]) == ("doc.pdf", pages[0], "T")
    assert report.total.hits["exact"] == report.total.cells - 1


def test_a_page_with_no_table_on_either_side_is_not_counted():
    sample, gold, extracted, pages, *_ = build()
    sample = Sample(1, 3, sample.drawn, sample.documents, [*sample.pages, (SHA, 99)])
    gold[key(SHA, 99)] = page_record(SHA, 99, [])
    report = evaluate(sample, gold, extracted)
    blank = next(p for p in report.pages if p.page == 99)
    assert not blank.counted
    assert report.units[2].either == len(pages)


def test_the_score_is_refused_until_every_sampled_page_is_done():
    sample, gold, extracted, pages, *_ = build()
    gold[key(SHA, pages[0])] = page_record(SHA, pages[0], [], done=False)
    status = progress(sample, gold)
    assert (status.done, status.total) == (len(pages) - 1, len(pages))
    assert status.left == [(SHA, pages[0])]
    assert not status.complete
    with pytest.raises(GoldError, match="are done"):
        evaluate(sample, gold, extracted)


def test_progress_of_an_untouched_sample_is_zero():
    sample, _, _, pages, *_ = build()
    assert progress(sample, {}).done == 0
    assert progress(sample, {}).left == sample.pages


def test_the_interval_is_a_point_when_every_page_of_the_document_is_sampled():
    sample, gold, extracted, *_ = build()
    interval = evaluate(sample, gold, extracted).interval
    assert interval is not None
    assert interval.low == interval.high == interval.share == 1.0


def test_the_interval_is_wider_for_a_smaller_share_of_the_document_and_holds_the_share():
    sample, gold, _, pages, columns, rows = build(pages_total=200)
    pred = copy.deepcopy(rows)
    pred[pages[0]][0][0] = "#### wrong"
    extracted = {SHA: (REF, [ExtractedTable(0, "T", columns, pred)])}
    wide = evaluate(sample, gold, extracted).interval
    small, gold2, extracted2, *_ = build(pages_total=len(pages) + 1)
    pred2 = copy.deepcopy(rows)
    pred2[pages[0]][0][0] = "#### wrong"
    narrow = evaluate(small, gold2, {SHA: (REF, [ExtractedTable(0, "T", columns, pred2)])}).interval
    assert wide is not None
    assert narrow is not None
    assert wide.low <= wide.share <= wide.high
    assert wide.share == narrow.share == (len(pages) - 1) / len(pages)
    assert narrow.high - narrow.low < wide.high - wide.low


def test_several_documents_give_pooled_counts_and_no_interval():
    sample, gold, extracted, pages, columns, rows = build()
    docs = [*sample.documents, SampleDoc(OTHER, "second.pdf", 4)]
    both = Sample(1, len(pages) + 1, sample.drawn, docs, [*sample.pages, (OTHER, 1)])
    gold[key(OTHER, 1)] = page_record(OTHER, 1, [GoldTable(["A"], [["x"], ["y"]])])
    extracted[OTHER] = (
        RunRef("s" * 32, "2026-11-10T00:00:00Z", "fake", "second.pdf"),
        [ExtractedTable(0, "T", ["A"], {1: [["x"], ["y"]]})],
    )
    report = evaluate(both, gold, extracted)
    assert report.interval is None
    assert sum(d.counts.cells for d in report.documents) == report.total.cells
    assert {d.name for d in report.documents} == {"doc.pdf", "second.pdf"}
    assert {t.name for t in report.tables} == {"doc.pdf", "second.pdf"}


def test_a_document_with_no_usable_run_is_listed_and_left_out():
    sample, gold, extracted, pages, *_ = build()
    docs = [*sample.documents, SampleDoc(OTHER, "second.pdf", 4)]
    both = Sample(1, len(pages) + 1, sample.drawn, docs, [*sample.pages, (OTHER, 1)])
    gold[key(OTHER, 1)] = page_record(OTHER, 1, [GoldTable(["A"], [["x"]])])
    report = evaluate(both, gold, extracted)
    assert report.not_scored == ["second.pdf"]
    assert all(p.sha256 == SHA for p in report.pages)
    assert report.interval is None


def test_table_lines_group_by_extracted_table_and_unmatched_gold():
    sample, gold, _, pages, columns, rows = build()
    pred = {p: [] for p in pages}
    pred[pages[0]] = [["unrelated"] * len(columns)]
    report = evaluate(sample, gold, {SHA: (REF, [ExtractedTable(0, "T", columns, pred)])})
    indexes = {t.index for t in report.tables}
    assert indexes == {0, None}
    unmatched = next(t for t in report.tables if t.index is None)
    assert unmatched.label == "(no match)"
    assert isinstance(TableRows, type)
