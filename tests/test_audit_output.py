"""What the omission audit leaves in the output: the `audit_added` column and the saved run."""

import json
from dataclasses import replace
from pathlib import Path

import pandas as pd
import polars as pl

from quotable.runs import list_runs, load_run
from quotable.steps.merge import merge_pair
from quotable.table import AuditItem, MergeEvidence, Table
from tests.table_builder import build_table
from tests.test_runs import save

COLUMNS = ["Item", "Amount"]
XS = [50.0, 250.0]


def rows(count: int = 3) -> list[dict[str, str]]:
    return [{"Item": f"Proj{r}", "Amount": f"${r}00"} for r in range(1, count + 1)]


def table_with_audit(tmp_path: Path, items: list[AuditItem], columns=COLUMNS) -> Table:
    data = [dict(zip(columns, row.values(), strict=True)) for row in rows()]
    table = build_table(tmp_path, columns, [data, data], xs=XS)
    return replace(table, audit=items)


ITEMS = [
    AuditItem(1, "row", {"Item": "Proj2", "Amount": "$200"}, "accepted", row=2),
    AuditItem(2, "cell", {"Amount": "$300"}, "accepted", row=3),
    AuditItem(2, "cell", {"Item": "Proj3"}, "accepted", row=3),
    AuditItem(2, "row", {"Item": "Nope", "Amount": "$9"}, "ungrounded"),
    AuditItem(1, "cell", {"Amount": "$100"}, "not_empty"),
]


def test_audit_added_names_an_added_row_and_the_cells_filled_in_table_order(tmp_path):
    marks = {
        (r["page"], r["row"]): r["audit_added"] for r in table_with_audit(tmp_path, ITEMS).records()
    }
    assert marks == {
        (1, 1): "",
        (1, 2): "row",
        (1, 3): "",
        (2, 1): "",
        (2, 2): "",
        (2, 3): "cells: Item, Amount",  # the table's column order, not the order proposed
    }


def test_the_column_comes_last_and_no_earlier_column_moves(tmp_path):
    plain = table_with_audit(tmp_path, [])
    marked = table_with_audit(tmp_path, ITEMS)
    assert list(marked.records()[0])[-1] == "audit_added"
    assert list(marked.records()[0])[:-1] == list(plain.records()[0])[:-1]
    assert {r["audit_added"] for r in plain.records()} == {""}


def test_a_pdf_column_with_the_same_name_keeps_its_name_and_the_library_adds_an_underscore(
    tmp_path,
):
    items = [AuditItem(1, "row", {"audit_added": "x", "Amount": "$200"}, "accepted", row=2)]
    columns = ["audit_added", "Amount"]
    records = table_with_audit(tmp_path, items, columns).records()
    assert records[1]["audit_added_"] == "row"
    assert records[1]["audit_added"] == "Proj2"  # the PDF's own column, untouched


def test_the_frames_carry_the_column_as_a_string(tmp_path):
    table = table_with_audit(tmp_path, ITEMS)
    pandas_frame, polars_frame = table.to_pandas(), table.to_polars()
    assert list(pandas_frame.columns)[-1] == list(polars_frame.columns)[-1] == "audit_added"
    assert pandas_frame["audit_added"].tolist() == polars_frame["audit_added"].to_list()
    assert pd.api.types.is_string_dtype(pandas_frame["audit_added"])
    assert polars_frame.schema["audit_added"] == pl.String


def test_merging_two_tables_keeps_the_audit_items_of_both(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    a = table_with_audit(tmp_path / "a", ITEMS[:1])
    data = rows()
    b = build_table(tmp_path / "b", COLUMNS, [data], xs=XS, first_page=3)
    b = replace(b, audit=[AuditItem(3, "row", data[0], "accepted", row=1)])
    merged = merge_pair(a, b, MergeEvidence())
    assert [(i.page, i.row) for i in merged.audit] == [(1, 2), (3, 1)]


# --- saved runs -------------------------------------------------------------------------------
def test_a_saved_run_holds_the_audit_items_and_the_two_settings(tmp_path):
    table = table_with_audit(tmp_path, ITEMS)
    project = tmp_path / "project"
    where, info, *_ = save(project, [table], tmp_path / "t.pdf", audit=True, sharp_images=False)
    stored = json.loads((where / "tables.json").read_text())["tables"][0]["audit"]
    assert [(a["page"], a["kind"], a["outcome"], a["row"]) for a in stored] == [
        (1, "row", "accepted", 2),
        (2, "cell", "accepted", 3),
        (2, "cell", "accepted", 3),
        (2, "row", "ungrounded", None),
        (1, "cell", "not_empty", None),
    ]
    settings = json.loads((where / "run.json").read_text())["run"]["settings"]
    assert (settings["audit"], settings["sharp_images"]) == (True, False)
    run = load_run(project, info.id)
    assert [a["outcome"] for a in run.tables[0].audit] == [i.outcome for i in ITEMS]
    assert run.summary.settings["audit"] is True


def test_a_run_saved_before_spec_014_still_loads_and_has_no_audit_items(tmp_path):
    table = table_with_audit(tmp_path, [])
    project = tmp_path / "project"
    where, info, *_ = save(project, [table], tmp_path / "t.pdf")
    big = json.loads((where / "tables.json").read_text())
    for entry in big["tables"]:
        del entry["audit"]
    (where / "tables.json").write_text(json.dumps(big))
    small = json.loads((where / "run.json").read_text())
    del small["run"]["settings"]["audit"], small["run"]["settings"]["sharp_images"]
    (where / "run.json").write_text(json.dumps(small))
    summaries, skipped = list_runs(project)
    assert [s.id for s in summaries] == [info.id] and skipped == 0
    assert load_run(project, info.id).tables[0].audit == []
