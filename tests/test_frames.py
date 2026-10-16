"""Table.records() column names (spec 008) and Table.to_pandas() / Table.to_polars()."""

import subprocess
import sys
from pathlib import Path

import pandas as pd
import polars as pl
import pytest

import quotable
from quotable.table import Table
from tests.conftest import extract_tables, load_sample, replay
from tests.table_builder import build_table

XS = [72.0, 182.0, 292.0, 402.0]


def small_table(tmp_path: Path, columns: list[str], rows: list[dict[str, str]]) -> Table:
    """One page of ``rows`` with the columns spread along the page."""
    return build_table(tmp_path, columns, [rows], xs=XS[: len(columns)])


@pytest.fixture
def table(tmp_path: Path) -> Table:
    """Two rows; the second has an empty Note, which is never looked up (coverage None)."""
    columns = ["Item", "Amount", "Note"]
    rows = [
        {"Item": "Alpha", "Amount": "$1,234", "Note": "red"},
        {"Item": "Beta", "Amount": "(12)", "Note": ""},
    ]
    return small_table(tmp_path, columns, rows)


@pytest.fixture
def empty_table() -> Table:
    return Table(columns=["Item", "Amount"], pages=[], layers={}, grounded={}, position={})


def default_names(columns: list[str]) -> list[str]:
    names = ["page", "row", *columns]
    for column in columns:
        names += [f"{column}__grounding", f"{column}__coverage"]
    return [*names, "grounding_status", "recheck_changes"]


# --- column names -----------------------------------------------------------------------


def test_without_a_collision_the_names_are_the_default_ones(table):
    assert list(table.records()[0]) == default_names(table.columns)


def test_a_pdf_column_called_page_keeps_its_text_and_the_page_number_is_page_(tmp_path):
    columns = ["page", "Amount"]
    rows = [{"page": "iv", "Amount": "$5"}, {"page": "v", "Amount": "$6"}]
    records = small_table(tmp_path, columns, rows).records()
    assert [r["page"] for r in records] == ["iv", "v"]
    assert [r["page_"] for r in records] == [1, 1]
    assert [r["row"] for r in records] == [1, 2]


def test_a_pdf_column_called_row_keeps_its_text(tmp_path):
    records = small_table(tmp_path, ["row", "Amount"], [{"row": "7", "Amount": "$5"}]).records()
    assert records[0]["row"] == "7"
    assert records[0]["row_"] == 1


def test_a_pdf_column_called_grounding_status_keeps_its_values(tmp_path):
    columns = ["grounding_status", "Amount"]
    records = small_table(tmp_path, columns, [{"grounding_status": "ok", "Amount": "$5"}]).records()
    assert records[0]["grounding_status"] == "ok"
    assert records[0]["grounding_status_"] == "exact"


def test_a_pdf_column_named_like_a_grounding_column_keeps_its_values(tmp_path):
    columns = ["Amount", "Amount__grounding"]
    rows = [{"Amount": "$5", "Amount__grounding": "yes"}]
    (record,) = small_table(tmp_path, columns, rows).records()
    assert record["Amount__grounding"] == "yes"
    assert record["Amount__grounding_"] == "exact"
    assert record["Amount__grounding__grounding"] == "exact"


def test_page_and_page_underscore_both_present_give_page_two_underscores(tmp_path):
    columns = ["page", "page_"]
    (record,) = small_table(tmp_path, columns, [{"page": "a", "page_": "b"}]).records()
    assert (record["page"], record["page_"], record["page__"]) == ("a", "b", 1)


def test_the_comparison_is_case_sensitive(tmp_path):
    (record,) = small_table(tmp_path, ["Page", "Amount"], [{"Page": "3", "Amount": "$5"}]).records()
    assert list(record)[:2] == ["page", "row"]
    assert record["Page"] == "3"
    assert record["page"] == 1


@pytest.mark.parametrize("library", ["pandas", "polars"])
def test_no_frame_has_a_duplicate_column_when_names_collide(tmp_path, library):
    columns = ["page", "row", "grounding_status", "recheck_changes"]
    rows = [dict.fromkeys(columns, "x")]
    frame = getattr(small_table(tmp_path, columns, rows), f"to_{library}")()
    assert len(set(frame.columns)) == len(frame.columns) == len(default_names(columns))
    assert list(frame.columns)[:2] == ["page_", "row_"]


# --- frames -----------------------------------------------------------------------------


def test_both_frames_have_the_columns_and_rows_of_records(table):
    records = table.records()
    for frame in (table.to_pandas(), table.to_polars()):
        assert list(frame.columns) == list(records[0])
        assert len(frame) == len(records)


def test_every_cell_equals_the_records_value(table):
    records = table.records()
    pandas_frame = table.to_pandas()
    polars_frame = table.to_polars()
    for name in records[0]:
        for i, record in enumerate(records):
            expected = record[name]
            if expected is None:
                assert pd.isna(pandas_frame[name][i])
                assert polars_frame[name][i] is None
            else:
                assert pandas_frame[name][i] == expected
                assert polars_frame[name][i] == expected


def test_values_stay_the_strings_the_model_gave(table):
    assert table.to_pandas()["Amount"].tolist() == ["$1,234", "(12)"]
    assert table.to_polars()["Amount"].to_list() == ["$1,234", "(12)"]


def test_dtypes_in_pandas(table):
    frame = table.to_pandas()
    assert frame["page"].dtype == "int64"
    assert frame["row"].dtype == "int64"
    assert frame["Amount__coverage"].dtype == "float64"
    for name in ("Item", "Item__grounding", "grounding_status", "recheck_changes"):
        assert pd.api.types.is_string_dtype(frame[name])
        assert frame[name].dtype != object


def test_dtypes_in_polars(table):
    schema = table.to_polars().schema
    assert schema["page"] == pl.Int64
    assert schema["row"] == pl.Int64
    assert schema["Amount__coverage"] == pl.Float64
    for name in ("Item", "Item__grounding", "grounding_status", "recheck_changes"):
        assert schema[name] == pl.String


def test_a_cell_that_was_never_looked_up_has_missing_coverage(table):
    assert table.records()[1]["Note__coverage"] is None
    assert pd.isna(table.to_pandas()["Note__coverage"][1])
    assert table.to_polars()["Note__coverage"][1] is None


def test_an_all_missing_coverage_column_is_still_float(tmp_path):
    table = small_table(tmp_path, ["Item", "Note"], [{"Item": "Alpha", "Note": ""}])
    assert table.to_pandas()["Note__coverage"].dtype == "float64"
    assert table.to_polars().schema["Note__coverage"] == pl.Float64


def test_a_table_without_rows_gives_empty_frames_with_every_column(empty_table):
    names = default_names(empty_table.columns)
    pandas_frame = empty_table.to_pandas()
    polars_frame = empty_table.to_polars()
    assert list(pandas_frame.columns) == list(polars_frame.columns) == names
    assert len(pandas_frame) == len(polars_frame) == 0
    assert pandas_frame["page"].dtype == "int64"
    assert pandas_frame["Item__coverage"].dtype == "float64"
    assert pandas_frame["Item"].dtype != object
    assert polars_frame.schema["page"] == pl.Int64
    assert polars_frame.schema["Item__coverage"] == pl.Float64
    assert polars_frame.schema["Item"] == pl.String


def test_each_call_gives_a_new_frame_and_leaves_the_table_alone(table):
    before = table.records()
    first = table.to_pandas()
    first.loc[0, "Item"] = "changed"
    assert table.to_pandas()["Item"][0] == "Alpha"
    assert table.to_pandas() is not table.to_pandas()
    assert table.to_polars().equals(table.to_polars())
    assert table.records() == before


def test_a_document_with_two_tables_gives_two_frames(tmp_path):
    first = small_table(tmp_path, ["Item", "Amount"], [{"Item": "Alpha", "Amount": "$1"}])
    second = build_table(
        tmp_path,
        ["Name", "Note"],
        [[{"Name": "Gamma", "Note": "red"}]],
        xs=XS[:2],
        name="u",
    )
    assert list(first.to_pandas().columns) != list(second.to_pandas().columns)
    assert list(second.to_polars().columns) == default_names(["Name", "Note"])


def test_a_table_from_the_pipeline_converts(sample):
    client = replay(sample["columns"], sample["pages"])
    (table,) = extract_tables(sample["pdf"], client, recheck=False)
    assert len(table.to_pandas()) == len(table.to_polars()) == len(table.rows())


def test_the_sample_frames_agree_with_each_other():
    sample = load_sample("fy22_milcon_house_original")
    (table,) = extract_tables(
        sample["pdf"], replay(sample["columns"], sample["pages"]), recheck=False
    )
    from_pandas = table.to_pandas().astype(object).where(lambda f: f.notna(), None)
    assert from_pandas.values.tolist() == [list(row) for row in table.to_polars().rows()]


def test_the_public_names_are_unchanged():
    assert "Table" in quotable.__all__
    assert not {"pandas", "polars", "to_pandas", "to_polars"} & set(quotable.__all__)


def test_importing_quotable_does_not_import_pandas_or_polars():
    code = "import sys, quotable; print('pandas' in sys.modules, 'polars' in sys.modules)"
    out = subprocess.run(  # noqa: S603
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    assert out.stdout.split() == ["False", "False"]
