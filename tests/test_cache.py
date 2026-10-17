"""The always-on cache directory: where it is, what is in it, and how it is written."""

import json
import os
from pathlib import Path

import pytest

from quotable import extract_tables
from quotable.cache import resolve_cache_dir, resolve_project_dir, write_atomic
from tests.test_entrypoint import PDF, Calls


def names(folder: Path) -> list[str]:
    return sorted(p.name for p in folder.iterdir())


def test_the_default_location_is_dot_quotable_cache_in_the_working_directory():
    extract_tables(PDF, Calls().model(), recheck=False)
    project = Path.cwd() / ".quotable"
    assert (project / ".gitignore").read_text() == "*\n"
    assert names(project) == [".gitignore", "cache"]
    answers = [n for n in names(project / "cache") if n.endswith(".json")]
    assert len(answers) == 2  # discovery and the one page
    assert names(Path.cwd()) == [".quotable"]


def test_a_named_cache_dir_gets_the_files_and_nothing_is_created_in_the_working_directory(
    tmp_path,
):
    cache = tmp_path / "named"
    extract_tables(PDF, Calls().model(), cache_dir=cache, recheck=False)
    assert len([n for n in names(cache) if n.endswith(".json")]) == 2
    assert ".gitignore" not in names(cache)
    assert names(Path.cwd()) == []


def test_an_existing_dot_quotable_is_not_given_a_gitignore():
    (Path.cwd() / ".quotable").mkdir()
    resolve_cache_dir(None)
    assert names(Path.cwd() / ".quotable") == ["cache"]


def test_the_default_directory_is_the_working_directory_at_the_time_of_the_call(
    tmp_path, monkeypatch
):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    assert resolve_cache_dir(None) == elsewhere / ".quotable" / "cache"


def test_the_project_folder_is_created_with_a_gitignore_only_when_missing(tmp_path, monkeypatch):
    fresh = tmp_path / "fresh"
    fresh.mkdir()
    monkeypatch.chdir(fresh)
    assert resolve_project_dir() == fresh / ".quotable"
    assert (fresh / ".quotable" / ".gitignore").read_text() == "*\n"
    existing = tmp_path / "existing"
    (existing / ".quotable").mkdir(parents=True)
    monkeypatch.chdir(existing)
    resolve_project_dir()
    assert names(existing / ".quotable") == []


def test_a_named_cache_dir_creates_no_project_folder(tmp_path):
    resolve_cache_dir(tmp_path / "named")
    assert names(Path.cwd()) == []


def test_a_file_where_the_project_folder_should_be_raises_oserror_naming_the_path():
    (Path.cwd() / ".quotable").write_text("x")
    with pytest.raises(OSError, match="quotable"):
        resolve_project_dir()


def make_old_cache(project: Path) -> dict[str, bytes]:
    """Lay out a cache the way quotable 0.1 did: answers and ``ocr/`` loose in ``.quotable/``."""
    project.mkdir(exist_ok=True)
    files = {
        f"{'a' * 64}.json": b'{"a": 1}',
        f"{'0f' * 32}.json": b'{"b": 2}',
        f"ocr/{'c' * 64}.json": b'{"c": 3}',
    }
    for name, data in files.items():
        (project / name).parent.mkdir(exist_ok=True)
        (project / name).write_bytes(data)
    return files


def test_an_old_cache_is_moved_into_the_cache_folder_once():
    project = Path.cwd() / ".quotable"
    files = make_old_cache(project)
    (project / ".gitignore").write_text("*\n")
    (project / "cost").mkdir()
    (project / "cost" / "requests.jsonl").write_text("{}\n")
    (project / "notes.txt").write_text("mine")
    (project / f"{'a' * 64}.json.tmp").write_text("partial")
    (project / "UPPER.json").write_text("mine")

    cache = resolve_cache_dir(None)

    assert cache == project / "cache"
    for name, data in files.items():
        assert (cache / name).read_bytes() == data
        assert not (project / name).exists()
    assert names(project) == [
        ".gitignore",
        "UPPER.json",
        f"{'a' * 64}.json.tmp",
        "cache",
        "cost",
        "notes.txt",
    ]
    assert (project / "cost" / "requests.jsonl").read_text() == "{}\n"


def test_the_move_is_not_repeated_once_the_cache_folder_exists():
    project = Path.cwd() / ".quotable"
    (project / "cache").mkdir(parents=True)
    make_old_cache(project)
    resolve_cache_dir(None)
    assert f"{'a' * 64}.json" in names(project)  # left alone: the first-run move is over


def test_a_run_after_the_move_finds_the_old_answers():
    extract_tables(PDF, Calls().model(), recheck=False)
    project = Path.cwd() / ".quotable"
    for entry in (project / "cache").iterdir():  # turn it back into an old-style cache
        entry.replace(project / entry.name)
    (project / "cache").rmdir()
    calls = Calls()
    extract_tables(PDF, calls.model(), recheck=False)
    assert calls.count == 0


def test_an_entry_that_cannot_be_moved_stays_and_one_warning_is_printed(monkeypatch, capsys):
    project = Path.cwd() / ".quotable"
    make_old_cache(project)
    real_replace = os.replace

    def refuse(src: str | os.PathLike[str], dst: str | os.PathLike[str]) -> None:
        if str(src).endswith(f"{'a' * 64}.json"):
            msg = "busy"
            raise PermissionError(msg)
        real_replace(src, dst)

    monkeypatch.setattr(os, "replace", refuse)
    cache = resolve_cache_dir(None)
    stuck = project / f"{'a' * 64}.json"
    assert stuck.exists()
    assert (cache / f"{'0f' * 32}.json").exists()
    assert (cache / "ocr").is_dir()
    err = capsys.readouterr().err
    assert err.count("\n") == 1
    assert "1" in err


def test_an_entry_already_moved_by_another_run_is_ignored(monkeypatch, capsys):
    project = Path.cwd() / ".quotable"
    make_old_cache(project)
    real_replace = os.replace

    def gone(src: str | os.PathLike[str], dst: str | os.PathLike[str]) -> None:
        if str(src).endswith(f"{'a' * 64}.json"):
            raise FileNotFoundError(src)
        real_replace(src, dst)

    monkeypatch.setattr(os, "replace", gone)
    resolve_cache_dir(None)
    assert capsys.readouterr().err == ""


def test_a_relative_cache_dir_resolves_against_the_working_directory():
    path = resolve_cache_dir("relative/cache")
    assert path.resolve() == (Path.cwd() / "relative" / "cache").resolve()
    assert path.is_dir()


@pytest.mark.skipif(os.geteuid() == 0, reason="root can write anywhere")
def test_an_unwritable_directory_raises_oserror_naming_the_path(tmp_path):
    locked = tmp_path / "locked"
    locked.mkdir()
    locked.chmod(0o500)
    try:
        with pytest.raises(OSError, match="locked") as error:
            resolve_cache_dir(locked / "cache")
    finally:
        locked.chmod(0o700)
    assert "cache_dir" in str(error.value)


def test_a_file_where_the_directory_should_be_raises_oserror_naming_the_path(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    with pytest.raises(OSError, match="file"):
        resolve_cache_dir(blocker)


def test_a_corrupt_model_answer_file_is_a_miss_and_is_overwritten(tmp_path):
    cache = tmp_path / "cache"
    extract_tables(PDF, Calls().model(), cache_dir=cache, recheck=False)
    (victim,) = [p for p in cache.glob("*.json") if "rows" in p.read_text()]
    victim.write_text("{not json")
    calls = Calls()
    extract_tables(PDF, calls.model(), cache_dir=cache, recheck=False)
    assert calls.count == 1  # only the corrupt one is asked again
    json.loads(victim.read_text())  # and it is valid again


def test_the_atomic_write_leaves_no_temporary_file(tmp_path):
    target = tmp_path / "sub" / "file.json"
    write_atomic(target, "{}")
    write_atomic(target, '{"a": 1}')
    assert target.read_text() == '{"a": 1}'
    assert names(target.parent) == ["file.json"]


def test_a_failed_atomic_write_leaves_the_old_file_and_no_temporary_file(tmp_path, monkeypatch):
    folder = tmp_path / "folder"
    folder.mkdir()
    target = folder / "file.json"
    write_atomic(target, "old")

    def boom(self: Path, other: object) -> None:
        msg = "disk full"
        raise OSError(msg)

    monkeypatch.setattr(Path, "replace", boom)
    with pytest.raises(OSError, match="disk full"):
        write_atomic(target, "new")
    monkeypatch.undo()
    assert target.read_text() == "old"
    assert names(folder) == ["file.json"]
