"""
Live check of spec 007 with a real model: reworded headers after a gap come back as one table.

The documents are the golden fixture's "Pipeline", "Controls" and interleaved cases; the
expectations come from their truth files, not from stored model answers. Each case runs three
times (separate cache directories, so each run asks the model again); a second call with
``merge_reworded=False`` reuses the cached answers (``max_requests=0`` proves it) and must give
the tables the pipeline gave before the merge step.

These cost money and need ``OPENAI_API_KEY`` and ``GRIDKEY_LIVE_TEST_MODEL``; run with
``uv run pytest -m live tests/live/test_live_merge.py``. A case where the real model reports a
header in a way the rules rightly refuse is a finding to report, not a test to loosen.
"""

import json
import os
from pathlib import Path

import pytest

from gridkey import extract_tables
from tests.fixture_tables import DATA, load_doc

MODEL = os.environ.get("GRIDKEY_LIVE_TEST_MODEL", "")

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        not (MODEL and os.environ.get("OPENAI_API_KEY")),
        reason="set OPENAI_API_KEY and GRIDKEY_LIVE_TEST_MODEL to run live tests",
    ),
]

CACHE = Path(__file__).parent / ".cache" / "merge"
RUNS = (1, 2, 3)
MIN_RECALL = 0.95  # share of the truth rows that must come back exactly

REWORDED = [  # one table, one absorbed part
    "pipe-reworded-gap0",
    "pipe-reworded-gap1",
    "pipe-reworded-gap4",
    "pipe-reworded-gap9",
    "pipe-reworded-gap20",
    "pipe-reworded-headerless",
    "pipe-reworded-lookalike",
    "pipe-long-parts",
]
ONE_TABLE = [  # one table already by discovery: the new step must not act
    "pipe-exact-gap0",
    "pipe-exact-gap4",
    "pipe-exact-gap20",
    "pipe-caps",
    "ctrl-single-table",
]
TWO_TABLES = {"ctrl-unrelated": 2, "struct-interleaved": 2}


def _truth_rows(doc_id: str) -> list[tuple[str, ...]]:
    return [
        tuple(row)
        for part in load_doc(doc_id)["parts"]
        for page in part["pages"]
        for row in part["rows"][str(page)]
    ]


def _got_rows(tables) -> list[tuple[str, ...]]:
    return [tuple(r.values.values()) for t in tables for r in t.rows()]


def _recall(doc_id: str, tables) -> float:
    wanted = _truth_rows(doc_id)
    remaining = _got_rows(tables)
    hits = 0
    for row in wanted:
        if row in remaining:
            remaining.remove(row)
            hits += 1
    return hits / len(wanted)


def _summary(tables) -> list[tuple]:
    return [(t.columns, [r.page for r in t.pages], len(t.merged)) for t in tables]


def _run(doc_id: str, run: int, *, merge_reworded: bool = True, max_requests: int | None = None):
    pages = load_doc(doc_id)["pages"]
    return extract_tables(
        DATA / f"{doc_id}.pdf",
        MODEL,
        cache_dir=CACHE / doc_id / f"run{run}",
        max_requests=pages * 3 + 12 if max_requests is None else max_requests,
        merge_reworded=merge_reworded,
    )


@pytest.mark.parametrize("run", RUNS)
@pytest.mark.parametrize("doc_id", REWORDED)
def test_a_reworded_table_comes_back_as_one(doc_id, run):
    tables = _run(doc_id, run)
    assert len(tables) == 1, _summary(tables)
    (table,) = tables
    assert len(table.merged) == 1, _summary(tables)
    assert _recall(doc_id, tables) >= MIN_RECALL
    assert len(table.rows()) <= len(_truth_rows(doc_id)) + 2

    separate = _run(doc_id, run, merge_reworded=False, max_requests=0)  # all from the cache
    assert len(separate) == 2
    assert all(t.merged == () for t in separate)


@pytest.mark.parametrize("run", RUNS)
@pytest.mark.parametrize("doc_id", ONE_TABLE)
def test_a_table_discovery_already_joined_is_left_alone(doc_id, run):
    tables = _run(doc_id, run)
    assert len(tables) == 1, _summary(tables)
    assert tables[0].merged == ()
    assert _recall(doc_id, tables) >= MIN_RECALL


@pytest.mark.parametrize("run", RUNS)
@pytest.mark.parametrize("doc_id", list(TWO_TABLES))
def test_different_tables_stay_apart_and_the_compatible_ones_join(doc_id, run):
    tables = _run(doc_id, run)
    assert len(tables) == TWO_TABLES[doc_id], _summary(tables)
    assert _recall(doc_id, tables) >= MIN_RECALL
    # ctrl-unrelated: nothing joins; struct-interleaved: A and B join, X stays alone
    expected = 0 if doc_id == "ctrl-unrelated" else 1
    assert sum(len(t.merged) for t in tables) == expected, _summary(tables)


def test_the_fixture_documents_exist():
    manifest = {e["id"] for e in json.loads((DATA / "manifest.json").read_text())}
    assert {*REWORDED, *ONE_TABLE, *TWO_TABLES} <= manifest
