"""The always-on cache directory: where it is, what is in it, and how it is written."""

import json
import os
from pathlib import Path

import pytest

from quotable import extract_tables
from quotable.cache import resolve_cache_dir, write_atomic
from tests.test_entrypoint import PDF, Calls


def names(folder: Path) -> list[str]:
    return sorted(p.name for p in folder.iterdir())


def test_the_default_location_is_dot_quotable_in_the_working_directory():
    extract_tables(PDF, Calls().model(), recheck=False)
    cache = Path.cwd() / ".quotable"
    assert (cache / ".gitignore").read_text() == "*\n"
    answers = [n for n in names(cache) if n.endswith(".json")]
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
    assert names(Path.cwd() / ".quotable") == []


def test_the_default_directory_is_the_working_directory_at_the_time_of_the_call(
    tmp_path, monkeypatch
):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    assert resolve_cache_dir(None) == elsewhere / ".quotable"


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
