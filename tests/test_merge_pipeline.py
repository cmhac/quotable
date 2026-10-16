"""The merge step inside the pipeline, with a fake client that answers from the truth files.

The fake model only drives the wiring (it reports each part's header as printed and returns
its rows); whether a real model does the same is the live check, `tests/live/test_live_merge.py`.
"""

import inspect

import pytest

import quotable
from quotable import extract, merge
from quotable.models import Column, PageRecheck, PageRows, PageTables, TableInfo
from tests.conftest import FakeClient, extract_tables, window_of
from tests.fixture_tables import DATA, load_doc


def client_for(doc_id: str, *, typos=None, recheck=None) -> tuple[FakeClient, dict]:
    """A fake model that reports the truth: tables per page, and each part's rows per page."""
    truth = load_doc(doc_id)
    by_page = {}
    rows = {}
    for part in truth["parts"]:
        for page in part["pages"]:
            by_page[page] = part
            rows[page] = [
                dict(zip(part["columns"], r, strict=True)) for r in part["rows"][str(page)]
            ]
    for (page, row, column), value in (typos or {}).items():
        rows[page][row - 1][column] = value
    seen = iter(range(1, truth["pages"] + 1))

    def handler(request):
        if request.stage == "schema":
            page = next(seen)  # discovery_pages=1: one page per request
            part = by_page.get(page)
            tables = (
                []
                if part is None
                else [
                    TableInfo(
                        label=part["id"],
                        columns=[Column(name=c, description="") for c in part["columns"]],
                        first_row="",
                        last_row="",
                    )
                ]
            )
            return window_of(request, [PageTables(tables=tables)])
        if request.stage == "extract":
            return PageRows(rows=[dict(r) for r in rows[request.page]])
        assert recheck is not None, "unexpected recheck request"
        return recheck(request)

    return FakeClient(handler), truth


def run(doc_id: str, **options):
    client, truth = client_for(
        doc_id, **{k: options.pop(k) for k in ("typos", "recheck") if k in options}
    )
    return extract_tables(DATA / f"{doc_id}.pdf", client, discovery_pages=1, **options), truth


def truth_rows(truth, part_index):
    part = truth["parts"][part_index]
    return [
        dict(zip(part["columns"], r, strict=True))
        for p in part["pages"]
        for r in part["rows"][str(p)]
    ]


def test_a_reworded_second_part_is_merged_by_default():
    tables, truth = run("pipe-reworded-gap1")
    (table,) = tables
    names = truth["parts"][0]["columns"]
    assert table.columns == names
    assert [r.page for r in table.pages] == [1, 2, 4, 5]
    assert [r.values for r in table.rows()] == truth_rows(truth, 0) + [
        dict(zip(names, r.values(), strict=True)) for r in truth_rows(truth, 1)
    ]
    assert {c.status for r in table.rows() for c in r.cells.values()} == {"exact"}
    assert [m.pages for m in table.merged] == [(4, 5)]
    assert table.merged[0].columns == tuple(truth["parts"][1]["columns"])


def test_switched_off_gives_two_tables_and_never_calls_the_merge(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("merge_tables was called")

    monkeypatch.setattr(extract, "merge_tables", forbidden)
    tables, truth = run("pipe-reworded-gap1", merge_reworded=False)
    assert [t.columns for t in tables] == [p["columns"] for p in truth["parts"]]
    assert all(t.merged == () for t in tables)


def test_the_off_switch_gives_what_the_pipeline_gave_before_the_step(monkeypatch):
    off, _ = run("pipe-reworded-gap1", merge_reworded=False)
    monkeypatch.setattr(extract, "merge_tables", lambda tables, **_: tables)
    never, _ = run("pipe-reworded-gap1")
    assert off == never


@pytest.mark.parametrize("doc_id", ["ctrl-unrelated", "ctrl-single-table", "pipe-exact-gap1"])
def test_a_document_where_nothing_merges_is_the_same_either_way(doc_id):
    on, _ = run(doc_id, merge_reworded=True)
    off, _ = run(doc_id, merge_reworded=False)
    assert on == off
    assert all(t.merged == () for t in on)


def test_the_recheck_runs_after_the_merge_and_fixes_a_cell_of_the_second_part():
    truth = load_doc("pipe-reworded-gap1")
    names = truth["parts"][0]["columns"]
    b_names = truth["parts"][1]["columns"]
    correct = truth["parts"][1]["rows"]["5"][2][0]  # 3rd row of page 5, first column
    wrong = correct.split()[0] + " Zzyzx"
    seen = []

    def recheck(request):
        seen.append(request.page)
        return PageRecheck(cells=[{"row": 3, "column": names[0], "value": correct}])

    tables, _ = run("pipe-reworded-gap1", typos={(5, 3, b_names[0]): wrong}, recheck=recheck)
    (table,) = tables
    assert seen == [5]
    assert table.page_rows(5)[2].values[names[0]] == correct
    assert [p.outcome for p in table.proposals] == ["accepted"]
    assert table.merged


def test_the_argument_is_keyword_only_and_on_by_default():
    for function in (quotable.extract_tables, quotable.extract_tables_async):
        parameter = inspect.signature(function).parameters["merge_reworded"]
        assert parameter.default is True
        assert parameter.kind is inspect.Parameter.KEYWORD_ONLY
    assert "merge_reworded" in inspect.signature(extract.run_pipeline).parameters
    assert merge.merge_tables is extract.merge_tables
