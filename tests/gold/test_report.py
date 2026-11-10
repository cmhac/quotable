"""The report as text, JSON and CSV (spec 016 tasks 011, 016 and 027)."""

import csv
import io
import json

from quotable.gold.report import cells_csv, format_text, pages_csv, to_json
from quotable.gold.score import ExtractedTable, RunRef, evaluate
from quotable.gold.store import GoldPage, GoldTable, Sample, SampleDoc, key

SHA = "a" * 64
REF = RunRef("r" * 32, "2026-11-10T00:00:00Z", "fake-model", "doc.pdf")


def report(pred_rows, gold_rows=None, *, columns=("Name", "Amount"), pred_columns=None):
    gold_rows = gold_rows or [["Ann", "1,000"], ["Bob", "2"]]
    sample = Sample(7, 1, "2026-11-10T00:00:00Z", [SampleDoc(SHA, "doc.pdf", 40)], [(SHA, 3)])
    gold = {
        key(SHA, 3): GoldPage(
            SHA, 3, [GoldTable(list(columns), gold_rows)], True, 9.0, "2026-11-10T00:00:00Z"
        )
    }
    table = ExtractedTable(0, "Table 1", list(pred_columns or columns), {3: pred_rows})
    return evaluate(sample, gold, {SHA: (REF, [table])})


def test_the_text_has_the_headline_table_definitions_run_and_interval():
    text = format_text(report([["Ann", "1000"], ["Bob", "3"]]))
    assert "1 gold pages from 1 documents" in text
    assert "doc.pdf: run rrrrrrrr (fake-model" in text
    assert "recall  precision  accuracy" in text
    assert "recall = correct / gold, precision = correct / extracted" in text
    assert "cell:  a cell with text" in text
    assert "cell accuracy at every level:" in text
    assert "pages correct: 0.0% of 1 counted pages, 95% interval" in text
    assert "an estimate for this document only" in text


def test_the_text_lists_how_every_column_was_paired():
    r = report(
        [["1,000", "Ann"], ["2", "Bob"]],
        columns=("Name", "Amount"),
        pred_columns=("Funding", "Place"),
    )
    text = format_text(r)
    assert "Name = Place [values]" in text
    assert "Amount = Funding [values]" in text
    r2 = report([["Ann", "1,000"], ["Bob", "2"]])
    assert "Name = Name [name]" in format_text(r2)


def test_a_gold_table_without_a_partner_is_named_in_the_text():
    r = report([["zzz", "yyy"]])
    assert "no extracted table" in format_text(r)


def test_to_json_is_plain_data_with_the_rates():
    data = to_json(report([["Ann", "1,000"], ["Bob", "2"]]))
    json.dumps(data)
    cell = next(u for u in data["units"] if u["name"] == "cell")
    assert (cell["recall"], cell["precision"], cell["accuracy"]) == (1.0, 1.0, 1.0)
    assert data["benchmark"] == "normal"
    assert data["interval"]["share"] == 1.0
    assert data["pages"][0]["pairs"][0]["columns"][0] == {
        "gold": "Name",
        "extracted": "Name",
        "how": "name",
    }


def test_pages_csv_has_one_line_per_counted_page():
    rows = list(csv.reader(io.StringIO(pages_csv(report([["Ann", "1,000"], ["Bob", "9"]])))))
    assert rows[0][:4] == ["document", "page", "correct", "gold_tables"]
    assert len(rows) == 2
    line = dict(zip(rows[0], rows[1], strict=True))
    assert (line["document"], line["page"], line["correct"]) == ("doc.pdf", "3", "False")
    assert (line["gold_rows"], line["matched_rows"], line["rows_correct"]) == ("2", "2", "1")
    assert (line["exact"], line["normal"]) == ("3", "3")


def test_cells_csv_has_one_line_per_non_exact_cell():
    rows = list(csv.reader(io.StringIO(cells_csv(report([["ANN", "1000"], ["Bob", "9"]])))))
    assert rows[0] == [
        "document",
        "page",
        "table",
        "column",
        "gold_row",
        "gold",
        "extracted",
        "best",
    ]
    found = {(r[3], r[4]): r[7] for r in rows[1:]}
    assert found == {("Name", "1"): "normal", ("Amount", "1"): "normal", ("Amount", "2"): "none"}


def test_a_cell_that_starts_like_a_formula_is_prefixed():
    r = report([["=SUM(A1)", "1,000"], ["Bob", "2"]], gold_rows=[["+1", "1,000"], ["Bob", "2"]])
    rows = list(csv.reader(io.StringIO(cells_csv(r))))
    assert rows[1][5] == "'+1"
    assert rows[1][6] == "'=SUM(A1)"


def test_an_extra_row_has_an_empty_gold_row_in_the_cells_csv():
    r = report([["Ann", "1,000"], ["Bob", "2"], ["Cy", "3"]])
    rows = list(csv.reader(io.StringIO(cells_csv(r))))
    assert [row[4] for row in rows[1:]] == ["", ""]
