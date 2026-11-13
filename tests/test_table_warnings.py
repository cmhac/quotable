"""Reading the data of a failed table returns what it holds and warns once per call (spec 019)."""

import warnings

import pytest

from quotable import Problem, TableFailedWarning
from tests.table_builder import build_table, failed_table

ROWS = [[{"A": "alpha", "B": "one"}, {"A": "beta", "B": "two"}]]
PROBLEM = Problem("extraction", (2,), "page 2: rows still invalid after one retry")


def record(call):
    """Return what ``call()`` returned and the TableFailedWarnings it emitted."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        result = call()
    return result, [w for w in caught if issubclass(w.category, TableFailedWarning)]


@pytest.fixture
def partly_failed(tmp_path):
    return failed_table("Costs", [PROBLEM], tmp_path=tmp_path, pages=ROWS)


def accessors(table):
    return {
        "rows()": table.rows,
        "page_rows()": lambda: table.page_rows(1),
        "records()": table.records,
        "to_pandas()": table.to_pandas,
        "to_polars()": table.to_polars,
        "flagged()": table.flagged,
    }


@pytest.mark.parametrize(
    "name", ["rows()", "page_rows()", "records()", "to_pandas()", "to_polars()", "flagged()"]
)
def test_each_accessor_warns_once_and_names_the_table_and_the_problem(partly_failed, name):
    _, caught = record(accessors(partly_failed)[name])
    assert len(caught) == 1
    text = str(caught[0].message)
    assert "table 'Costs' failed" in text
    assert PROBLEM.message in text
    assert name in text
    assert "may be incomplete or wrong" in text


def test_a_failed_table_still_returns_what_it_holds(partly_failed):
    rows, _ = record(partly_failed.rows)
    assert [r.values["A"] for r in rows] == ["alpha", "beta"]
    records, _ = record(partly_failed.records)
    assert [r["A"] for r in records] == ["alpha", "beta"]


def test_the_descriptive_fields_do_not_warn(partly_failed):
    def read():
        return (
            partly_failed.label,
            partly_failed.columns,
            partly_failed.pages,
            partly_failed.problems,
            partly_failed.failed,
        )

    (label, columns, _, problems, failed), caught = record(read)
    assert (label, columns, problems, failed) == ("Costs", ["A", "B"], [PROBLEM], True)
    assert caught == []


def test_a_sound_table_never_warns(tmp_path):
    table = build_table(tmp_path, ["A", "B"], ROWS, xs=[50.0, 200.0])
    for call in accessors(table).values():
        assert record(call)[1] == []


def test_a_table_that_holds_nothing_gives_empty_results_and_one_warning():
    table = failed_table("Empty")
    for name in ("rows()", "records()", "flagged()"):
        result, caught = record(accessors(table)[name])
        assert result == [] and len(caught) == 1
    frame, caught = record(table.to_pandas)
    assert len(frame) == 0 and len(caught) == 1
    frame, caught = record(table.to_polars)
    assert frame.height == 0 and len(caught) == 1


def test_an_unnamed_table_is_called_unnamed():
    _, caught = record(failed_table("").records)
    assert "table 'unnamed' failed" in str(caught[0].message)


def test_several_problems_are_all_named(tmp_path):
    problems = [PROBLEM, Problem("extraction", (4,), "page 4: rows still invalid after one retry")]
    table = failed_table("Costs", problems, tmp_path=tmp_path, pages=ROWS)
    _, caught = record(table.records)
    text = str(caught[0].message)
    assert "page 2:" in text and "page 4:" in text


def test_a_page_the_table_does_not_hold_is_a_key_error_not_a_failure_error(partly_failed):
    with pytest.raises(KeyError):
        record(lambda: partly_failed.page_rows(99))


def test_the_filters_decide_whether_reading_raises(partly_failed):
    with warnings.catch_warnings():
        warnings.simplefilter("error", TableFailedWarning)
        with pytest.raises(TableFailedWarning, match="table 'Costs' failed"):
            partly_failed.records()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", TableFailedWarning)
        assert len(partly_failed.records()) == 2
