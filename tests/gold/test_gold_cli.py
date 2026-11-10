"""``quotable gold-report`` (spec 016 tasks 013 and 044)."""

import csv
import hashlib
from pathlib import Path

import pytest

from quotable.__main__ import main
from quotable.gold.store import GoldStore, GoldTable, SampleStore
from quotable.storage import ensure_gold_trackable
from tests.gold_project import draw_and_type
from tests.review.test_browse_api import Built, snapshot


def first_cell_changed(page: int, tables: list[GoldTable]) -> list[GoldTable]:
    if page != 1 or not tables:
        return tables
    first = tables[0]
    rows = [list(r) for r in first.rows]
    rows[0][0] = "#### " + rows[0][0]
    return [GoldTable(first.columns, rows), *tables[1:]]


def test_a_perfect_gold_scores_100_percent_and_writes_two_csv_files(
    built: Built, project: Path, capsys: pytest.CaptureFixture[str]
):
    draw_and_type(project, built.runs["simple_new"])
    assert main(["gold-report"]) == 0
    out = capsys.readouterr().out
    assert "scored at the 'normal' cell level" in out
    assert "100.0%" in out
    pages, cells = project / "reports" / "gold_pages.csv", project / "reports" / "gold_cells.csv"
    assert pages.exists()
    assert len(list(csv.reader(cells.open()))) == 1  # the header only
    assert f"wrote {pages} and {cells}" in out


def test_a_changed_cell_shows_in_the_report_and_the_cells_file(
    built: Built, project: Path, capsys: pytest.CaptureFixture[str]
):
    draw_and_type(project, built.runs["simple_new"], change=first_cell_changed)
    assert main(["gold-report", "--out", str(project / "elsewhere")]) == 0
    capsys.readouterr()
    rows = list(csv.DictReader((project / "elsewhere" / "gold_cells.csv").open()))
    assert len(rows) == 1
    assert rows[0]["gold"].startswith("#### ")
    assert rows[0]["best"] in {"fuzzy", "none"}
    assert not (project / "reports").exists()


def test_no_sample_exits_one_with_a_message(project: Path, capsys: pytest.CaptureFixture[str]):
    assert main(["gold-report"]) == 1
    assert "no sample has been drawn" in capsys.readouterr().err


def test_an_incomplete_sample_exits_one_and_says_how_many_are_done(
    built: Built, project: Path, capsys: pytest.CaptureFixture[str]
):
    sample = draw_and_type(project, built.runs["simple_new"], done=False)
    assert main(["gold-report"]) == 1
    err = capsys.readouterr().err
    assert f"0 of {len(sample.pages)} sampled pages are done" in err
    assert not (project / "reports").exists()


def test_an_unreadable_gold_file_exits_one_and_is_left_alone(
    built: Built, project: Path, capsys: pytest.CaptureFixture[str]
):
    draw_and_type(project, built.runs["simple_new"])
    store = GoldStore(project)
    store.path.write_text("{broken", encoding="utf-8")
    assert main(["gold-report"]) == 1
    assert "not valid JSON" in capsys.readouterr().err
    assert store.path.read_text(encoding="utf-8") == "{broken"


def test_a_usage_error_exits_two():
    with pytest.raises(SystemExit) as stop:
        main(["gold-report", "--no-such-option"])
    assert stop.value.code == 2


def test_gold_report_never_changes_runs_cache_cost_or_reviews(
    built: Built, project: Path, capsys: pytest.CaptureFixture[str]
):
    draw_and_type(project, built.runs["simple_new"])
    watched = ("runs", "cache", "cost", "review")
    before = {n: snapshot(project / n) for n in watched if (project / n).exists()}
    assert main(["gold-report"]) == 0
    capsys.readouterr()
    after = {n: snapshot(project / n) for n in watched if (project / n).exists()}
    assert before == after


def test_the_newest_run_is_the_default_and_run_chooses_another(
    built: Built, project: Path, capsys: pytest.CaptureFixture[str]
):
    older, newer = built.runs["simple_old"], built.runs["simple_new"]
    draw_and_type(project, older)
    assert main(["gold-report"]) == 0
    assert f"run {newer[:8]}" in capsys.readouterr().out
    assert main(["gold-report", "--run", older]) == 0
    assert f"run {older[:8]}" in capsys.readouterr().out


def test_two_runs_of_one_document_and_an_unknown_run_exit_one(
    built: Built, project: Path, capsys: pytest.CaptureFixture[str]
):
    older, newer = built.runs["simple_old"], built.runs["simple_new"]
    draw_and_type(project, older)
    assert main(["gold-report", "--run", older, "--run", newer]) == 1
    assert "same document" in capsys.readouterr().err
    assert main(["gold-report", "--run", "f" * 32]) == 1
    assert "no saved run" in capsys.readouterr().err


def test_a_run_of_a_document_with_no_gold_is_left_out_with_a_note(
    built: Built, project: Path, capsys: pytest.CaptureFixture[str]
):
    draw_and_type(project, built.runs["simple_new"])
    assert main(["gold-report", "--run", built.runs["senate"]]) == 0
    assert "its document has no gold" in capsys.readouterr().out


def test_nothing_is_stored_between_two_scores(
    built: Built, project: Path, capsys: pytest.CaptureFixture[str]
):
    draw_and_type(project, built.runs["simple_new"])
    gold_files = list((project / "gold").iterdir())
    before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in gold_files}
    main(["gold-report"])
    main(["gold-report"])
    capsys.readouterr()
    after = {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (project / "gold").iterdir()
    }
    assert before == after
    assert SampleStore(project).load() is not None


def test_a_gold_folder_git_may_ignore_is_reported_after_the_report(
    built: Built, project: Path, capsys: pytest.CaptureFixture[str]
):
    draw_and_type(project, built.runs["simple_new"])
    (project / ".gitignore").write_text("*.pdf\n")
    assert main(["gold-report"]) == 0
    captured = capsys.readouterr()
    assert "gold folder" in captured.err
    assert captured.err.startswith("quotable: ")
    assert "scored at the" in captured.out


def test_nothing_is_reported_when_the_gold_folder_is_trackable_or_nothing_ignores_it(
    built: Built, project: Path, capsys: pytest.CaptureFixture[str]
):
    draw_and_type(project, built.runs["simple_new"])
    ensure_gold_trackable(project)
    assert main(["gold-report"]) == 0
    assert capsys.readouterr().err == ""
    (project / ".gitignore").unlink()
    assert main(["gold-report"]) == 0
    assert capsys.readouterr().err == ""
