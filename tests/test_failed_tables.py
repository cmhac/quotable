"""One table that fails does not cost the others (spec 019, Stories 1, 3 and 4)."""

import asyncio
import warnings
from pathlib import Path

import pytest

from quotable import BudgetExceededError, ExtraField, ExtraFields, TableFailedWarning
from quotable.llm.answers import ExtraValue, PageRows, PageWithExtras, WindowWithExtras
from quotable.llm.client import CachedClient
from quotable.llm.images import TODAY
from quotable.pipeline import RunTrace, _save_run, run_pipeline
from quotable.runs import load_run
from quotable.steps.audit import audit_table
from quotable.steps.recheck import recheck_table
from tests.conftest import FakeClient, extract_tables
from tests.table_builder import failed_table
from tests.test_cost_limit import Run
from tests.test_tables import A_ROWS, B_ROWS, STACKED_A, STACKED_B, info, model

HEADER_A = [(72, 60, "Item"), (182, 60, "Amount"), (72, 90, "Alpha"), (182, 90, "$100")]
HEADER_B = [(72, 60, "Name"), (182, 60, "Amount"), (292, 60, "Note")]
HEADER_C = [(72, 60, "Code"), (182, 60, "Value"), (72, 90, "X1"), (182, 90, "42")]
C_ROWS = [{"Code": "X1", "Value": "42"}]
ROWS = {("Item", 1): A_ROWS[:1], ("Name", 2): B_ROWS[:1], ("Code", 3): C_ROWS}
PAGE_B = [*HEADER_B, (72, 90, "Gamma"), (182, 90, "$100"), (292, 90, "red")]


def a():
    return info(["Item", "Amount"], "A")


def b():
    return info(["Name", "Amount", "Note"], "B")


def c():
    return info(["Code", "Value"], "C")


def bad(label):
    return info([], label)


def run_with(path, client, **options):
    """Run the pipeline; return the tables and the TableFailedWarnings it emitted."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        tables = extract_tables(path, client, **options)
    return tables, [w for w in caught if issubclass(w.category, TableFailedWarning)]


def run(path, client):
    return run_with(path, client, recheck=False)


def test_a_table_with_no_columns_after_the_retry_comes_back_failed_beside_the_sound_ones(make_pdf):
    path = make_pdf([HEADER_A, PAGE_B, HEADER_C])
    window = [[a()], [bad("B")], [c()]]
    client = model([window, window], ROWS)  # the second answer is the answer to the retry

    tables, caught = run(path, client)

    assert [t.label for t in tables] == ["A", "B", "C"]
    assert [t.failed for t in tables] == [False, True, False]
    failed = tables[1]
    assert [(p.stage, p.pages) for p in failed.problems] == [("discovery", (2,))]
    assert "no columns" in failed.problems[0].message
    assert len(caught) == 1
    assert "table 'B' failed (pages 2)" in str(caught[0].message)
    assert "no columns" in str(caught[0].message)
    assert sorted(r.page for r in client.requests if r.stage == "extract") == [1, 3]


def test_the_sound_tables_equal_those_of_the_same_document_without_the_failing_table(make_pdf):
    window = [[a()], [bad("B")], [c()]]
    with_b, _ = run(make_pdf([HEADER_A, PAGE_B, HEADER_C]), model([window, window], ROWS))
    other = [[a()], [], [c()]]  # the same pages, the second one with no table at all
    without_b, _ = run(make_pdf([HEADER_A, [(72, 60, "Hello")], HEADER_C]), model([other], ROWS))
    assert with_b[0].records() == without_b[0].records()
    assert with_b[2].records() == without_b[1].records()
    assert with_b[0].flagged() == without_b[0].flagged()


def test_when_every_table_fails_the_call_still_returns_them(make_pdf):
    path = make_pdf([HEADER_A, PAGE_B, HEADER_C])
    window = [[bad("A")], [bad("B")], [bad("C")]]
    client = model([window, window], ROWS)
    tables, caught = run(path, client)
    assert [t.failed for t in tables] == [True, True, True]
    assert len(caught) == 3
    assert [r for r in client.requests if r.stage == "extract"] == []


def test_a_call_with_no_failure_has_no_failed_table_and_no_warning(make_pdf):
    path = make_pdf([HEADER_A, PAGE_B, HEADER_C])
    client = model([[[a()], [b()], [c()]]], ROWS)
    tables, caught = run(path, client)
    assert [t.failed for t in tables] == [False, False, False] and caught == []
    assert client.stages() == ["schema", "extract", "extract", "extract"]


def test_a_sound_table_keeps_its_own_band_on_a_page_a_failed_table_shares(make_pdf):
    path = make_pdf([STACKED_A + STACKED_B])
    sound = info(["Item", "Amount"], "A", "Alpha $100", "Beta $250")
    failed = info([], "B", "Gamma $100 red", "Delta $900 blue")
    client = model([[[sound, failed]]] * 2, {("Item", 1): A_ROWS})

    tables, caught = run(path, client)

    first, second = tables
    assert (first.failed, second.failed) == (False, True) and len(caught) == 1
    assert [w.text for w in first.layers[1].words] == ["Alpha", "$100", "Beta", "$250"]


def test_the_save_path_of_a_call_handles_a_failed_table(make_pdf, capsys):
    path = make_pdf([HEADER_A, PAGE_B, HEADER_C])
    window = [[a()], [bad("B")], [c()]]
    trace = RunTrace()
    with warnings.catch_warnings(record=True):
        warnings.simplefilter("always")
        tables = asyncio.run(
            run_pipeline(path, model([window, window], ROWS), recheck=False, trace=trace)
        )
    _save_run(
        "a" * 32,
        "2026-11-13T10:00:00Z",
        path,
        "test:fake",
        tables,
        trace,
        discovery_pages=4,
        recheck=False,
        audit=False,
        sharp_images=False,
        ocr=True,
        merge_reworded=True,
        max_requests=None,
        extra_fields=None,
    )
    assert "could not save" not in capsys.readouterr().err
    saved = load_run(Path(".quotable"), "a" * 32)
    assert [t.failed for t in saved.tables] == [False, True, False]


# --- failures after discovery (Story 4) ---------------------------------------------------------
PAGE_2 = [(72, 60, "Beta"), (182, 60, "$250")]
PAGE_3 = [(72, 60, "Gamma"), (182, 60, "$300")]
A_THREE = {
    ("Item", 1): A_ROWS[:1],
    ("Item", 2): [{"Item": "Beta", "Amount": "$250"}],
    ("Item", 3): [{"Item": "Gamma", "Amount": "$300"}],
    ("Code", 4): C_ROWS,
}
WRONG_KEYS = [{"Oops": "x"}]  # never the table's columns, however often it is asked


def problems_of(table):
    return [(p.stage, p.pages) for p in table.problems]


def test_rows_still_invalid_on_one_page_fail_that_table_and_keep_its_other_pages(make_pdf):
    path = make_pdf([HEADER_A, PAGE_2, PAGE_3, HEADER_C])
    rows = {**A_THREE, ("Item", 2): WRONG_KEYS}
    client = model([[[a()], [a()], [a()], [c()]]], rows)

    (first, second), caught = run(path, client)

    assert (first.label, first.failed, second.failed) == ("A", True, False)
    assert problems_of(first) == [("extraction", (2,))]
    assert "page 2: rows still invalid after one retry" in first.problems[0].message
    assert [r.page for r in first.pages] == [1, 3]  # the pages that did extract
    assert [r.values["Item"] for r in first._rows()] == ["Alpha", "Gamma"]
    assert len(caught) == 1 and "table 'A' failed (pages 2)" in str(caught[0].message)
    assert len([r for r in client.requests if r.stage == "extract" and r.page == 2]) == 2


def test_a_table_whose_every_page_is_invalid_comes_back_with_no_pages(make_pdf):
    path = make_pdf([HEADER_A, PAGE_2, HEADER_C])
    rows = {("Item", 1): WRONG_KEYS, ("Item", 2): WRONG_KEYS, ("Code", 3): C_ROWS}
    tables, caught = run(path, model([[[a()], [a()], [c()]]], rows))
    assert [t.failed for t in tables] == [True, False]
    assert tables[0].pages == [] and problems_of(tables[0]) == [("extraction", (1, 2))]
    assert len(caught) == 1


def test_two_overlapping_tables_both_fail_and_a_third_stays_sound(make_pdf):
    path = make_pdf([STACKED_A + STACKED_B, HEADER_C])
    long_a = info(["Item", "Amount"], "A", "Alpha $100", "Delta $900 blue")
    b_info = info(["Name", "Amount", "Note"], "B", "Gamma $100 red", "Delta $900 blue")
    client = model([[[long_a, b_info], [c()]]], {("Code", 2): C_ROWS})

    tables, caught = run(path, client)

    assert [t.failed for t in tables] == [True, True, False]
    assert problems_of(tables[0]) == problems_of(tables[1]) == [("location", (1,))]
    assert "'A' and 'B' overlap" in tables[0].problems[0].message
    assert len(caught) == 2
    assert sorted(r.page for r in client.requests if r.stage == "extract") == [2]


def test_a_row_not_found_on_a_shared_page_fails_only_its_table(make_pdf):
    path = make_pdf([STACKED_A + STACKED_B])
    sound = info(["Item", "Amount"], "A", "Alpha $100", "Beta $250")
    lost = info(["Name", "Amount", "Note"], "B", "Omega 1", "Delta $900 blue")
    client = model([[[sound, lost]]], {("Item", 1): A_ROWS})

    (first, second), caught = run(path, client)

    assert (first.failed, second.failed) == (False, True) and len(caught) == 1
    assert problems_of(second) == [("location", (1,))]
    assert "its first row was not found" in second.problems[0].message
    # the sound table still gets its own band, not the whole page
    assert [w.text for w in first.layers[1].words] == ["Alpha", "$100", "Beta", "$250"]
    assert client.stages() == ["schema", "extract"]


def test_a_cap_or_a_cost_limit_in_extraction_is_not_turned_into_a_problem(make_pdf, tmp_path):
    path = make_pdf([HEADER_A, PAGE_B, HEADER_C])
    inner = model([[[a()], [b()], [c()]]], ROWS)
    with pytest.raises(BudgetExceededError):
        extract_tables(path, CachedClient(inner, tmp_path / "cache", max_requests=1))


def test_a_failure_in_the_sample_warns_once_for_the_whole_call(tmp_path):
    run_ = Run(tmp_path)
    base = run_.handler

    def handler(request):
        if request.stage == "extract" and request.page == 1:
            return PageRows(rows=WRONG_KEYS)
        return base(request)

    run_.handler = handler
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        (table,) = run_.go(audit=False, recheck=False)
    assert table.failed and problems_of(table) == [("extraction", (1,))]
    assert [r.page for r in table.pages] == [2, 3, 4]
    assert len([w for w in caught if issubclass(w.category, TableFailedWarning)]) == 1


def test_later_stages_leave_a_failed_table_alone(make_pdf):
    path = make_pdf([HEADER_A, PAGE_2, HEADER_C])
    wrong = [{"Item": "Zzzz", "Amount": "$100"}]  # ungrounded: a recheck would be asked for it
    rows = {("Item", 1): wrong, ("Item", 2): WRONG_KEYS, ("Code", 3): C_ROWS}
    client = model([[[a()], [a()], [c()]]], rows)  # a recheck request would fail the test
    (first, _), _ = run_with(path, client, recheck=True, audit=False)
    assert first.failed and first.proposals == [] and "recheck" not in client.stages()


def test_recheck_and_audit_return_a_failed_table_as_it_is(tmp_path):
    table = failed_table("F", tmp_path=tmp_path, pages=[[{"A": "zzz", "B": "yyy"}]])
    gate = asyncio.Semaphore(1)

    def refuse(request):
        raise AssertionError("a failed table must cost no request")

    client = FakeClient(refuse)
    pdf = tmp_path / "none.pdf"
    assert asyncio.run(recheck_table(table, pdf, client, TODAY, gate)) is table
    assert asyncio.run(audit_table(table, pdf, client, TODAY, gate)) is table
    assert client.requests == []


def test_extra_fields_ignore_a_table_that_failed_in_discovery(make_pdf):
    path = make_pdf([HEADER_A, PAGE_B])
    division = ExtraField("division", "The division named at the top left")
    value = [ExtraValue(name="division", value=None)]
    window = [
        PageWithExtras(tables=[a()], extras=value),
        PageWithExtras(tables=[bad("B")], extras=value),
    ]
    answers = iter([WindowWithExtras(pages=window)] * 2)

    def handler(request):
        if request.stage == "schema":
            return next(answers)
        return PageRows(rows=A_ROWS[:1])

    with warnings.catch_warnings(record=True):
        warnings.simplefilter("always")
        tables = asyncio.run(
            run_pipeline(
                path, FakeClient(handler), recheck=False, extra_fields=ExtraFields([division])
            )
        )
    assert [t.failed for t in tables] == [False, True]
    assert tables[0].extra_names == ("division",) and tables[1].extra_names == ()
