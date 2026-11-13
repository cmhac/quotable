"""
Live check with a real model: discovery never answers a table with no columns.

Two windows of the 2025 Trump annual report (an OGE 278e filing) came back from the model as
tables with ``columns: []`` although every page prints a header row and the table was already
known from earlier pages: pages 357-360 (investment transactions) and 889-892 (trademark
registrations). ``tests/data/discovery_empty_columns/`` holds those eight pages and the tables
discovery had found before each window (``known_tables.json``; a table with no columns is left
out, it is the bug). Each window is asked three times, each in its own cache directory, so the
model answers again every run.

Costs a few cents. Needs ``OPENAI_API_KEY`` and ``QUOTABLE_LIVE_TEST_MODEL``. Run with
``just test-live tests/live/test_live_discovery_columns.py``.
"""

import asyncio
import json
import os
import shutil
from pathlib import Path

import pymupdf
import pytest

from quotable.llm.answers import Column, TableSchema
from quotable.llm.client import CachedClient, PydanticAIClient
from quotable.steps.discover import Found, _ask_window, signature
from quotable.steps.extract import render_png
from tests.conftest import DATA

MODEL = os.environ.get("QUOTABLE_LIVE_TEST_MODEL", "")

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        not (MODEL and os.environ.get("OPENAI_API_KEY")),
        reason="set OPENAI_API_KEY and QUOTABLE_LIVE_TEST_MODEL to run live tests",
    ),
]

FIXTURE = DATA / "discovery_empty_columns"
CACHE = Path(__file__).parent / ".cache" / "discovery_columns"
# first page of the window -> the columns every table of its four pages must have
EXPECTED = {
    357: ["#", "Description", "Type", "Date", "Amount"],
    889: [
        "Registered Owner",
        "Country",
        "Trademark Name",
        "Status",
        "Registration No.",
        "Class/Description",
    ],
}


def _known(first: int) -> list[Found]:
    found = []
    for t in json.loads((FIXTURE / "known_tables.json").read_text())[str(first)]:
        schema = TableSchema(columns=[Column(name=n, description="") for n in t["columns"]])
        found.append(Found("", schema, dict.fromkeys(t["pages"], ("", ""))))
    return found


@pytest.mark.parametrize("run", [1, 2, 3])
@pytest.mark.parametrize("first", sorted(EXPECTED))
def test_a_window_of_known_table_pages_is_answered_with_columns(first: int, run: int):
    pages = list(range(first, first + 4))
    with pymupdf.open(FIXTURE / f"pages_{first}_{first + 3}.pdf") as document:
        # discovery indexes images by page number; only this window's four are ever read
        images = [b""] * (first - 1) + [render_png(p) for p in document]
    cache = CACHE / f"{first}-{run}"
    shutil.rmtree(cache, ignore_errors=True)  # a cached answer would hide a model that changed
    cache.mkdir(parents=True)
    client = CachedClient(PydanticAIClient(MODEL), cache)

    entries = asyncio.run(_ask_window(images, pages, _known(first), client))

    got = [[c.name for c in t.columns] for e in entries for t in e.tables]
    assert got, "no table reported"
    assert all(signature(g) == signature(EXPECTED[first]) for g in got), got
