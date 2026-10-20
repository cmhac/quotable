"""The demo project for working on the review app (spec 013 task 009): built offline, never rots."""

import json
from pathlib import Path

import pytest

from quotable.review import sources
from quotable.review.verdicts import CellKey, VerdictStore
from quotable.runs import Run, list_runs, load_run
from quotable.storage import CostRecord, cost_file
from tests import review_demo

SMALL = 1  # pages of the large table: the test needs the wiring, not the size


@pytest.fixture(scope="module")
def project(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return review_demo.build(tmp_path_factory.mktemp("demo"), large_pages=SMALL)


def all_runs(project: Path) -> list[Run]:
    summaries, _ = list_runs(project)
    return [load_run(project, s.id) for s in summaries]


def test_the_defaults_are_a_git_ignored_folder_and_a_table_of_several_thousand_rows():
    assert Path("build/review-demo") == review_demo.DEFAULT_DIR
    assert review_demo.LARGE_PAGES * review_demo.LARGE_ROWS_PER_PAGE >= 3000


def test_list_runs_sees_every_run_of_the_demo(project):
    summaries, unreadable = list_runs(project)
    assert unreadable == 0
    assert sorted(s.name for s in summaries) == sorted(review_demo.RUNS)
    assert project.name == ".quotable"


def test_everything_the_app_shows_is_there(project):
    runs = all_runs(project)
    tables = [(r, t) for r in runs for t in r.summary.tables]
    # two tables of one document, on one page
    shared = [r for r in runs if len(r.summary.tables) == 2 and r.summary.pages == 3]
    assert {r.summary.name for r in shared} == {
        review_demo.TWO_TABLES_PDF,
        review_demo.OCR_PDF,
    }
    for run in shared:
        assert set(run.tables[0].pages) & set(run.tables[1].pages)
    # extra fields carried over pages
    assert any(t.extra_names for _, t in tables)
    # a merged table
    assert any(t.merged > 0 for _, t in tables)
    # a table with the rows of every page the large document has
    (large,) = [r for r in runs if r.summary.name == review_demo.LARGE_PDF]
    assert large.summary.rows == review_demo.LARGE_ROWS_PER_PAGE * SMALL
    # an OCR'd page
    assert any(r.summary.ocr_pages for r in runs)


def test_every_status_appears(project):
    seen: set[str] = set()
    for run in all_runs(project):
        for table in run.tables:
            seen |= {c.status for row in table.rows for c in row.cells.values()}
            seen |= {e.cell.status for page in table.extra_fields.values() for e in page.values()}
    assert seen >= {
        "exact",
        "fuzzy",
        "ungrounded",
        "misplaced",
        "untokenized",
        "empty",
        "not_on_page",
    }


def test_a_document_was_run_twice_and_a_verdict_of_the_first_run_is_stale_in_the_second(project):
    named = sorted(
        (s for s in list_runs(project)[0] if s.name == review_demo.STALE_PDF),
        key=lambda s: s.started,
    )
    assert len(named) == 2
    first, second = (load_run(project, s.id) for s in named)
    assert first.summary.sha256 == second.summary.sha256
    store = VerdictStore(project)
    verdicts = [v for v in store.latest().values() if v.run == first.summary.id]
    assert len(verdicts) == 1
    (verdict,) = verdicts
    assert isinstance(verdict.key, CellKey)
    table = second.tables[verdict.table_index]
    now = next(
        r.values[verdict.key.column]
        for r in table.rows
        if (r.page, r.row) == (verdict.key.page, verdict.key.row)
    )
    assert now != verdict.extracted
    assert store.apply(verdict.key, now)[0] == "stale"
    # the same key in the first run is reviewed
    before = next(
        r.values[verdict.key.column]
        for r in first.tables[verdict.table_index].rows
        if (r.page, r.row) == (verdict.key.page, verdict.key.row)
    )
    assert store.apply(verdict.key, before)[0] == "reviewed"


def test_there_are_a_few_verdicts_of_every_kind(project):
    verdicts = list(VerdictStore(project).latest().values())
    assert {v.verdict for v in verdicts} == {"correct", "changed", "unsure"}
    assert all(v.category for v in verdicts if v.verdict == "changed")


def test_one_run_is_free_one_has_no_known_price_and_the_rest_have_a_price(project):
    summaries, _ = list_runs(project)
    kinds = {s.name: sources.cost_of(project, s.id)["kind"] for s in summaries}
    assert set(kinds.values()) == {"free", "unknown", "usd"}
    lines = cost_file(project).read_text(encoding="utf-8").splitlines()
    assert all(CostRecord.from_line(line).v == 1 for line in lines)


def test_one_pdf_is_missing_and_one_changed(project):
    summaries, _ = list_runs(project)
    found = [sources.pdf_status(s)["status"] for s in summaries]
    assert found.count("missing") == 1
    assert found.count("changed") == 1
    assert found.count("ok") == len(found) - 2


def test_building_again_over_a_demo_replaces_it(tmp_path):
    root = tmp_path / "demo"
    first = review_demo.build(root, large_pages=SMALL)
    marker = first / "review" / "stray.txt"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("left over")
    again = review_demo.build(root, large_pages=SMALL)
    assert again == first
    assert not marker.exists()
    assert len(list_runs(again)[0]) == len(review_demo.RUNS)


def test_a_folder_that_is_not_a_demo_is_never_deleted(tmp_path):
    (tmp_path / "precious.txt").write_text("mine")
    with pytest.raises(SystemExit, match="not a demo"):
        review_demo.build(tmp_path, large_pages=SMALL)
    assert (tmp_path / "precious.txt").read_text() == "mine"


def test_the_demo_makes_no_network_request_and_needs_no_key(monkeypatch, tmp_path):
    for name in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    project = review_demo.build(tmp_path / "demo", large_pages=SMALL)
    data = json.loads((next((project / "runs").iterdir()) / "run.json").read_text())
    assert data["run"]["model"].startswith("demo:")
