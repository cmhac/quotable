"""Drawing the gold sample (spec 015 task 006)."""

import pytest

from quotable.gold.sample import allocate, draw, make_sample, newest_by_document
from quotable.gold.store import Invalid, SampleDoc

A, B, C = "a" * 64, "b" * 64, "c" * 64
DOCS = [SampleDoc(A, "long.pdf", 100), SampleDoc(B, "mid.pdf", 9), SampleDoc(C, "one.pdf", 1)]


def test_every_document_gets_a_page_and_long_ones_get_more():
    counts = allocate({"a": 1, "b": 4, "c": 100}, 6)
    assert sum(counts.values()) == 6
    assert counts["a"] == 1  # capped at its size
    assert counts["c"] > counts["b"] >= 1


def test_too_few_or_too_many_pages_is_refused():
    with pytest.raises(Invalid, match="cannot draw"):
        allocate({"a": 5, "b": 5}, 1)
    with pytest.raises(Invalid, match="cannot draw"):
        allocate({"a": 5, "b": 5}, 11)


def test_the_draw_has_no_repeats_and_covers_every_document():
    pages = draw(DOCS, 10, 7)
    assert len(pages) == len(set(pages)) == 10
    assert {sha for sha, _ in pages} == {A, B, C}
    assert all(1 <= p <= {A: 100, B: 9, C: 1}[sha] for sha, p in pages)


def test_the_same_seed_repeats_the_draw_and_another_seed_differs():
    assert draw(DOCS, 10, 7) == draw(DOCS, 10, 7)
    assert draw(DOCS, 10, 7) != draw(DOCS, 10, 8)


def test_the_order_of_the_documents_given_does_not_matter():
    assert draw(DOCS, 10, 7) == draw(list(reversed(DOCS)), 10, 7)


def test_pages_are_sorted_within_each_document_and_documents_follow_name_order():
    pages = draw(DOCS, 12, 3)
    names = [sha for sha, _ in pages]
    assert names == sorted(names, key=lambda s: {A: "long", B: "mid", C: "one"}[s])
    for sha in (A, B):
        mine = [p for s, p in pages if s == sha]
        assert mine == sorted(mine)


def test_a_sample_records_what_it_was_drawn_from():
    sample = make_sample(DOCS, 5, 42)
    assert (sample.seed, sample.size) == (42, 5)
    assert [d.name for d in sample.documents] == ["long.pdf", "mid.pdf", "one.pdf"]
    assert len(sample.pages) == 5
    assert sample.has(*sample.pages[0])


def test_the_newest_run_of_each_document_is_chosen():
    class Run:
        def __init__(self, id_: str, sha: str) -> None:
            self.id, self.sha256 = id_, sha

    runs = [Run("new", A), Run("other", B), Run("old", A)]  # newest first, as list_runs gives
    assert {sha: r.id for sha, r in newest_by_document(runs).items()}  # ty: ignore[invalid-argument-type] == {A: "new", B: "other"}
