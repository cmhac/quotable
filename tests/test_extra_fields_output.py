"""Extra fields on rows, in records() and in the frames; counted like any grounded text."""

import asyncio
from dataclasses import replace
from pathlib import Path

import pandas as pd
import polars as pl
import pytest

from quotable.steps.extra_fields import ExtraResult
from quotable.steps.grounding import FieldGrounding
from quotable.steps.recheck import recheck_table
from quotable.table import Table, output_names
from tests.conftest import FakeClient
from tests.table_builder import build_table

XS = [72.0, 182.0]
COLUMNS = ["Item", "Amount"]
ROWS = [
    [{"Item": "Alpha", "Amount": "$1"}, {"Item": "Beta", "Amount": "$2"}],
    [{"Item": "Gamma", "Amount": "$3"}],
]


def result(value, source, status="exact", coverage=1.0):
    return ExtraResult(value, source, FieldGrounding(status, coverage))


MISSING = ExtraResult()


def make(tmp_path: Path, extras: dict[int, dict[str, ExtraResult]], changes=None) -> Table:
    table = build_table(tmp_path, COLUMNS, ROWS, xs=XS)
    names = tuple(next(iter(extras.values()))) if extras else ()
    return replace(table, extra_fields=extras, extra_names=names, extra_changes=changes or {})


@pytest.fixture
def table(tmp_path):
    return make(
        tmp_path,
        {
            1: {"division": result("Roads", 1), "year": MISSING},
            2: {"division": result("Roads", 1), "year": result("2018", 2)},
        },
    )


def test_every_row_has_the_results_of_its_page(table):
    assert [r.extra["division"].source_page for r in table.rows()] == [1, 1, 1]
    assert [r.extra["year"].value for r in table.rows()] == ["", "", "2018"]
    assert table.extra_fields[2]["year"].source_page == 2


def test_records_put_the_fields_after_the_values_and_before_the_groundings(table):
    first = table.records()[0]
    assert list(first) == [
        "page",
        "row",
        "Item",
        "Amount",
        "division",
        "year",
        "Item__grounding",
        "Item__coverage",
        "Amount__grounding",
        "Amount__coverage",
        "division__grounding",
        "division__coverage",
        "division__source_page",
        "year__grounding",
        "year__coverage",
        "year__source_page",
        "grounding_status",
        "recheck_changes",
    ]
    assert (first["division"], first["division__grounding"], first["division__source_page"]) == (
        "Roads",
        "exact",
        1,
    )
    assert (first["year"], first["year__grounding"], first["year__source_page"]) == (
        "",
        "empty",
        None,
    )
    assert first["year__coverage"] is None
    assert table.records()[2]["year__source_page"] == 2


def test_without_extra_fields_the_columns_are_the_old_ones(tmp_path):
    plain = build_table(tmp_path, COLUMNS, ROWS, xs=XS)
    assert list(plain.records()[0]) == [
        "page",
        "row",
        "Item",
        "Amount",
        "Item__grounding",
        "Item__coverage",
        "Amount__grounding",
        "Amount__coverage",
        "grounding_status",
        "recheck_changes",
    ]


def test_a_field_named_like_a_pdf_column_gets_a_trailing_underscore():
    names = output_names(["Item", "Amount"], ["Item", "division"])
    assert names.fields == {"Item": "Item_", "division": "division"}
    assert (
        names.field_grounding["Item"] == "Item__grounding_"
    )  # the PDF column's own grounding column came first


def test_a_field_called_page_keeps_its_name_and_the_page_number_becomes_page_(tmp_path):
    table = make(tmp_path, {1: {"page": result("iv", 1)}, 2: {"page": result("iv", 1)}})
    first = table.records()[0]
    assert (first["page"], first["page_"]) == ("iv", 1)


def test_library_columns_that_collide_with_a_field_column_get_a_trailing_underscore():
    names = output_names(["Item"], ["grounding_status", "Item__grounding"])
    assert names.fields["grounding_status"] == "grounding_status"
    assert names.status == "grounding_status_"
    assert names.grounding["Item"] == "Item__grounding_"


def test_pandas_has_a_nullable_integer_source_page(table):
    frame = table.to_pandas()
    assert str(frame["division__source_page"].dtype) == "Int64"
    assert str(frame["division"].dtype) in ("str", "string", "object")
    assert frame["division__coverage"].dtype == "float64"
    assert frame["year__source_page"].tolist()[:2] == [pd.NA, pd.NA]
    assert frame["year__source_page"].tolist()[2] == 2
    assert list(frame.columns) == list(table.records()[0])


def test_polars_has_a_nullable_integer_source_page(table):
    frame = table.to_polars()
    assert frame.schema["division__source_page"] == pl.Int64
    assert frame.schema["division"] == pl.String
    assert frame.schema["division__coverage"] == pl.Float64
    assert frame["year__source_page"].to_list() == [None, None, 2]
    assert frame.columns == list(table.records()[0])


def test_a_table_with_no_rows_still_has_the_field_columns(tmp_path):
    table = Table(
        columns=COLUMNS,
        pages=[],
        layers={},
        grounded={},
        position={},
        extra_names=("division",),
    )
    assert table.to_pandas().columns.tolist()[:4] == ["page", "row", "Item", "Amount"]
    assert "division__source_page" in table.to_pandas().columns
    assert "division__source_page" in table.to_polars().columns


def test_an_ungrounded_field_makes_every_row_that_carries_it_ungrounded(tmp_path):
    table = make(
        tmp_path,
        {
            1: {"division": result("Raods", 1, "ungrounded", 0.0)},
            2: {"division": result("Raods", 1, "ungrounded", 0.0)},
        },
    )
    assert [r.status for r in table.rows()] == ["ungrounded"] * 3
    assert [r["grounding_status"] for r in table.records()] == ["ungrounded"] * 3
    flags = table.flagged()
    assert [(f.page, f.row, f.column, f.status, f.extra) for f in flags] == [
        (1, 1, "division", "ungrounded", True),
        (1, 2, "division", "ungrounded", True),
        (2, 1, "division", "ungrounded", True),
    ]


def test_a_fuzzy_field_is_the_rows_worst_status_but_not_worse_than_a_cell(tmp_path):
    table = make(
        tmp_path, {1: {"division": result("Roads", 1, "fuzzy", 0.8)}, 2: {"division": MISSING}}
    )
    assert [r.status for r in table.rows()] == ["fuzzy", "fuzzy", "exact"]


def test_a_missing_field_flags_nothing(table):
    assert table.flagged() == []


def test_the_cell_recheck_ignores_a_flagged_field(tmp_path):
    table = make(
        tmp_path,
        {
            1: {"division": result("Raods", 1, "ungrounded", 0.0)},
            2: {"division": result("Raods", 1, "ungrounded", 0.0)},
        },
    )

    def refuse(_request):
        msg = "no request expected"
        raise AssertionError(msg)

    client = FakeClient(refuse)
    out = asyncio.run(recheck_table(table, tmp_path / "t.pdf", client))
    assert client.requests == []
    assert out is table


def test_an_accepted_change_is_in_recheck_changes_of_each_row_that_carries_it(tmp_path):
    table = make(
        tmp_path,
        {1: {"division": result("Roads", 1)}, 2: {"division": result("Roads", 1)}},
        {(1, "division"): ("Raods", "Roads")},
    )
    assert [r["recheck_changes"] for r in table.records()] == ['division: "Raods" -> "Roads"'] * 3


def test_a_merged_table_has_the_fields_of_the_pages_of_both_parts(tmp_path):
    from quotable.steps.merge import merge_pair  # noqa: PLC0415
    from quotable.table import MergeEvidence  # noqa: PLC0415

    one = build_table(tmp_path, ["Item", "Amount"], ROWS, xs=XS, name="a")
    rows_b = [[{"Item": r["Item"], "Amount Total": r["Amount"]} for r in page] for page in ROWS]
    two = build_table(tmp_path, ["Item", "Amount Total"], rows_b, xs=XS, name="b", first_page=3)
    names = ("division",)
    one = replace(
        one,
        extra_names=names,
        extra_fields={1: {"division": result("Roads", 1)}, 2: {"division": result("Roads", 1)}},
    )
    two = replace(
        two,
        extra_names=names,
        extra_fields={3: {"division": result("Parks", 3)}, 4: {"division": result("Parks", 3)}},
        extra_changes={(3, "division"): ("Prks", "Parks")},
    )
    merged = merge_pair(one, two, MergeEvidence())
    assert merged.extra_names == names
    assert sorted(merged.extra_fields) == [1, 2, 3, 4]
    assert [r["division"] for r in merged.records()] == ["Roads"] * 3 + ["Parks"] * 3
    assert merged.extra_changes == {(3, "division"): ("Prks", "Parks")}
