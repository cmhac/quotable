"""The review queue reads each run once and builds its items once (spec 015, story 3)."""

import shutil
from pathlib import Path

import pytest

from quotable.review import queue, review, sources
from quotable.review.review import get_queue
from quotable.review.routing import Request
from quotable.runs import RUN_FILE, TABLES_FILE
from tests.review.test_browse_api import Built, edit_run

ALL = {"statuses": ["exact,fuzzy,misplaced,ungrounded,untokenized"]}  # as parse_qs gives it
CLONES = 10


def clone(project: Path, source: str, n: int) -> str:
    """Copy a run under a new id and give it a new document hash: one more document."""
    new = f"{n:032x}"
    shutil.copytree(project / "runs" / source, project / "runs" / new)

    def change(data: dict) -> None:
        data["run"]["id"] = new
        data["document"]["sha256"] = f"{n:064x}"

    edit_run(project, new, small=change)
    return new


@pytest.fixture
def project(built: Built) -> tuple[Path, list[str]]:
    """A copy of the built project with ``CLONES`` more documents, and their run ids."""
    target = Path.cwd() / ".quotable"
    shutil.copytree(built.project, target)
    sources.clear_caches()
    return target, [clone(target, built.runs["senate"], n + 1) for n in range(CLONES)]


@pytest.fixture
def reads(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Run ids read from disk, in order."""
    found: list[str] = []
    real = sources.load_run

    def counting(project: Path, run_id: str):
        found.append(run_id)
        return real(project, run_id)

    monkeypatch.setattr(sources, "load_run", counting)
    return found


def queue_of(project: Path) -> dict:
    return get_queue(Request(project, (), ALL, None))


def test_a_second_queue_request_reads_no_run_file(project, reads):
    path, _ = project
    queue_of(path)
    assert len(reads) >= CLONES  # the first request had to read them
    reads.clear()
    queue_of(path)
    assert reads == []


def test_a_run_whose_file_changed_is_read_again_and_nothing_else(project, reads):
    path, ids = project
    queue_of(path)
    reads.clear()
    edit_run(path, ids[3], small=lambda d: d["document"].__setitem__("name", "renamed.pdf"))
    entries = queue_of(path)["queue"]
    assert reads == [ids[3]]
    assert {e["name"] for e in entries if e["run"] == ids[3]} == {"renamed.pdf"}


def stamp_size(path: Path, run_id: str) -> int:
    return sum((path / "runs" / run_id / n).stat().st_size for n in (RUN_FILE, TABLES_FILE))


def test_the_least_recently_used_run_goes_when_the_budget_is_full(project, reads, monkeypatch):
    path, ids = project
    a, b, c = ids[:3]
    monkeypatch.setattr(sources, "_RUN_BYTES", 2 * stamp_size(path, a) + 1)  # room for two
    for run_id in (a, b, c):
        sources.load(path, run_id)
    reads.clear()
    sources.load(path, b)
    sources.load(path, c)
    assert reads == []
    sources.load(path, a)  # went first
    assert reads == [a]


def test_a_run_over_the_whole_budget_is_still_kept_while_it_is_the_one_in_use(
    project, reads, monkeypatch
):
    path, ids = project
    monkeypatch.setattr(sources, "_RUN_BYTES", 1)
    sources.load(path, ids[0])
    sources.load(path, ids[0])
    assert reads == [ids[0]]
    sources.load(path, ids[1])  # now the other one is the only one kept
    sources.load(path, ids[1])
    assert reads == [ids[0], ids[1]]


def test_one_queue_request_builds_the_item_list_once(project, monkeypatch):
    path, _ = project
    calls = []
    real = queue.scoped_items

    def counting(runs, settings):
        calls.append(1)
        return real(runs, settings)

    monkeypatch.setattr(queue, "scoped_items", counting)
    if hasattr(review, "scoped_items"):  # imported by name into review.py
        monkeypatch.setattr(review, "scoped_items", counting)
    queue_of(path)
    assert len(calls) == 1
