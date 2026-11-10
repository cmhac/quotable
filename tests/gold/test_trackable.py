"""Making only the gold folder committable (spec 016 task 003)."""

import shutil
import subprocess
from pathlib import Path

import pytest

from quotable.storage import GOLD_IGNORE, IGNORE_ALL, ensure_gold_trackable


def test_quotables_own_ignore_file_is_upgraded(tmp_path: Path):
    (tmp_path / ".gitignore").write_text(IGNORE_ALL)
    assert ensure_gold_trackable(tmp_path) is None
    assert (tmp_path / ".gitignore").read_text() == GOLD_IGNORE


def test_a_missing_ignore_file_is_written(tmp_path: Path):
    assert ensure_gold_trackable(tmp_path) is None
    assert (tmp_path / ".gitignore").read_text() == GOLD_IGNORE


def test_the_upgrade_is_idempotent(tmp_path: Path):
    ensure_gold_trackable(tmp_path)
    assert ensure_gold_trackable(tmp_path) is None
    assert (tmp_path / ".gitignore").read_text() == GOLD_IGNORE


def test_other_content_is_left_alone_and_reported(tmp_path: Path):
    (tmp_path / ".gitignore").write_text("*.pdf\n")
    note = ensure_gold_trackable(tmp_path)
    assert note is not None
    assert "gold folder" in note
    assert (tmp_path / ".gitignore").read_text() == "*.pdf\n"


def test_an_unwritable_folder_is_reported_not_raised(tmp_path: Path):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    note = ensure_gold_trackable(blocker)  # a file where the folder should be
    assert note is not None


@pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")
def test_git_lists_the_ignore_file_and_the_gold_and_nothing_else(tmp_path: Path):
    project = tmp_path / ".quotable"
    (project / "gold").mkdir(parents=True)
    (project / "runs").mkdir()
    (project / ".gitignore").write_text(IGNORE_ALL)
    (project / "gold" / "pages.json").write_text("{}")
    (project / "runs" / "a.json").write_text("{}")
    (project / "cache.json").write_text("{}")
    ensure_gold_trackable(project)
    git = shutil.which("git") or "git"
    subprocess.run([git, "init", "-q"], cwd=tmp_path, check=True)  # noqa: S603
    out = subprocess.run(  # noqa: S603
        [git, "add", "-A", "-n"], cwd=tmp_path, check=True, capture_output=True, text=True
    ).stdout
    listed = sorted(line.split("'")[1] for line in out.splitlines())
    assert listed == [".quotable/.gitignore", ".quotable/gold/pages.json"]
