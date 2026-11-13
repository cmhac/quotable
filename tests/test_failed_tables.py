"""One table that fails does not cost the others (spec 019, Stories 1, 3 and 4)."""

import asyncio
import warnings
from pathlib import Path

from quotable import TableFailedWarning
from quotable.pipeline import RunTrace, _save_run, run_pipeline
from quotable.runs import load_run
from tests.conftest import extract_tables
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


def run(path, client):
    """Run the pipeline; return the tables and the TableFailedWarnings it emitted."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        tables = extract_tables(path, client, recheck=False)
    return tables, [w for w in caught if issubclass(w.category, TableFailedWarning)]


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
