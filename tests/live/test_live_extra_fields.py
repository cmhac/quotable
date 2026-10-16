"""
Live check of spec 010 with a real model: do extra fields read, carry and cost what they should?

Three groups of tests. Regression: asking for extra fields must not change the tables that
discovery and extraction give (columns, pages, rows). Accuracy on the ``extra-*`` fixture
documents: per page and field, the printed value, the carried value and its source page equal
the truth, no value is invented, and no missed header remains after the second look; the
documents the spec marks as known blind spots (``expect_stale``, ``expect_blind``) are
reported, never asserted. A slice of the real report (``QUOTABLE_LIVE_EXTRA_PDF``) gets the same
numbers.

The requests describe each field by its position only (``tests/extra_fields_live.py``): a
description that named a word of the header would hand the model the answer. Each test checks
that before it spends anything.

These cost money and need ``OPENAI_API_KEY`` and ``QUOTABLE_LIVE_TEST_MODEL``; never run them
without the owner's go-ahead. Run with
``uv run pytest -m live -s tests/live/test_live_extra_fields.py``. The numbers are printed and
kept in ``tests/live/.cache/extra/report-*.json``. Each case runs three times in separate cache
directories, so each run asks the model again. A difference is a finding to report, not a
test to loosen.

To go faster, add ``-n 4`` (pytest-xdist): the cases are independent, each with its own cache
directory and report file, so they run side by side. Each worker keeps up to 4 requests in
flight, so ``-n 4`` can mean 16 at once; lower it if the provider answers with rate-limit
errors. ``QUOTABLE_LIVE_RUNS=1`` runs each case once instead of three times (a first look; it
cannot show run-to-run differences).

The real slice also needs ``QUOTABLE_LIVE_EXTRA_LABEL`` (text printed on exactly the pages that
start a section). It takes ``QUOTABLE_LIVE_EXTRA_FIRST_PAGE`` (default 1),
``QUOTABLE_LIVE_EXTRA_LINES`` (how many lines the header block has, default 3) and
``QUOTABLE_LIVE_EXTRA_BOX`` (``x0,y0,x1,y1`` of the header, default ``0,0,260,130``; it is used
only to check that the request does not repeat the header's words).
"""

import asyncio
import json
import os
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pymupdf
import pytest

from quotable import extract_tables
from quotable._model import PydanticAIClient
from quotable.cache import resolve_cache_dir
from quotable.extra_fields import ExtraFields
from quotable.extract import run_pipeline
from quotable.grounding import find_candidates
from quotable.llm import CachedClient, Image, LLMClient, Request
from quotable.models import WindowWithExtras
from quotable.table import Table
from quotable.text import load_layer, tokenize
from tests.conftest import DATA as SAMPLES
from tests.extra_fields_live import (
    described_request,
    live_runs,
    neutral_fields,
    overlap,
    words_in_box,
)
from tests.fixture_tables import DATA, doc_ids, load_doc

MODEL = os.environ.get("QUOTABLE_LIVE_TEST_MODEL", "")

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        not (MODEL and os.environ.get("OPENAI_API_KEY")),
        reason="set OPENAI_API_KEY and QUOTABLE_LIVE_TEST_MODEL to run live tests",
    ),
]

CACHE = Path(__file__).parent / ".cache" / "extra"
RUNS = live_runs(os.environ.get("QUOTABLE_LIVE_RUNS"))
EXTRA_IDS = [i for i in doc_ids() if i.startswith("extra-")]
SENATE = SAMPLES / "senate_expenditures_paddleocr.pdf"
# documents with no header at all: the request must not change their tables
REGRESSION_FIXTURE = [
    "pipe-reworded-gap4",
    "ctrl-single-table",
    "struct-interleaved",
    "ctrl-unrelated",
]


STARTED = time.monotonic()
REQUESTS = [0]  # new model requests (the paid ones; cached answers are not counted) in this process
# (under ``-n`` each worker counts its own, and every progress line names its worker)
CONFIG: list[pytest.Config] = []


def progress(message: str) -> None:
    """
    Print a timestamped progress line on the terminal, whatever pytest's capture is doing.

    pytest captures file descriptor 2 as well as ``sys.stderr``, so writing to either is silent
    without ``-s``; the capture manager is told to step aside for the one line.
    """
    elapsed = int(time.monotonic() - STARTED)
    worker = os.environ.get("PYTEST_XDIST_WORKER")  # "gw0", "gw1", ... under ``-n``
    tag = f"live {elapsed // 60:02d}:{elapsed % 60:02d}" + (f" {worker}" if worker else "")
    line = f"[{tag}] {message}\n"
    manager = CONFIG[0].pluginmanager.getplugin("capturemanager") if CONFIG else None
    if manager is None:
        sys.stderr.write(line)
        sys.stderr.flush()
        return
    with manager.global_and_fixture_disabled():
        sys.stderr.write(line)
        sys.stderr.flush()


@pytest.fixture(autouse=True)
def announce(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Report each test's start and end, and every new model request it makes."""
    CONFIG[:] = [request.config]
    real_ask = PydanticAIClient.ask

    async def ask(self: PydanticAIClient, req: Request) -> Any:  # noqa: ANN401
        began = time.monotonic()
        progress(f"  model request {REQUESTS[0] + 1}: {req.stage} page {req.page} ...")
        answer = await real_ask(self, req)
        REQUESTS[0] += 1
        progress(f"  model request {REQUESTS[0]} answered in {time.monotonic() - began:.1f}s")
        return answer

    monkeypatch.setattr(PydanticAIClient, "ask", ask)
    before, began = REQUESTS[0], time.monotonic()
    progress(f"start  {request.node.name}")
    yield
    took = time.monotonic() - began
    progress(f"end    {request.node.name}: {took:.0f}s, {REQUESTS[0] - before} new requests")


class Recording:
    """Wrap the real client and note every request and answer, to count what the checks cost."""

    def __init__(self, inner: LLMClient) -> None:
        self.inner = inner
        self.identity = inner.identity
        self.log: list[tuple[Request, Any]] = []

    async def ask(self, request: Request) -> Any:  # noqa: ANN401
        answer = await self.inner.ask(request)
        self.log.append((request, answer))
        return answer


def run_pipeline_live(pdf: Path, request: ExtraFields, cache: Path, cap: int):
    """Run the pipeline with the real model; return the tables and the recording."""
    directory = resolve_cache_dir(cache)
    client = Recording(CachedClient(PydanticAIClient(MODEL), directory, cap))
    tables = asyncio.run(
        run_pipeline(pdf, client, extra_fields=request, ocr=None, cache_dir=directory)
    )
    return tables, client


def rows_of(tables: list[Table]) -> list[tuple[str, ...]]:
    """
    Return every row's values, with a comma read as a period.

    On a scan the two are hard to tell apart (the PDF's own text layer has both for the same
    printed comma), so the model's reading of one flips from run to run. Nothing else is
    loosened: a different letter, word or case still differs.
    """
    return [tuple(v.replace(",", ".") for v in r.values.values()) for t in tables for r in t.rows()]


def shape_of(tables: list[Table]) -> list[tuple]:
    return [(t.columns, [r.page for r in t.pages]) for t in tables]


def pages_of(pdf: Path) -> int:
    with pymupdf.open(pdf) as document:
        return document.page_count


# --- regression: asking for extra fields leaves the tables alone ------------------------------
@pytest.mark.parametrize("run", RUNS)
@pytest.mark.parametrize("source", ["senate", *REGRESSION_FIXTURE])
def test_asking_for_extra_fields_does_not_change_the_tables(source, run):
    pdf = SENATE if source == "senate" else DATA / f"{source}.pdf"
    request = ExtraFields(neutral_fields(3 if source == "senate" else 1))
    pages = pages_of(pdf)
    cap = pages * 3 + 12
    progress(f"  {source} run{run}: without extra fields")
    plain = extract_tables(
        pdf, MODEL, cache_dir=CACHE / "base" / source / f"run{run}", max_requests=cap, ocr=False
    )
    progress(f"  {source} run{run}: with extra fields")
    asked = extract_tables(
        pdf,
        MODEL,
        cache_dir=CACHE / "with" / source / f"run{run}",
        max_requests=cap * 2,
        ocr=False,
        extra_fields=request,
    )
    assert shape_of(asked) == shape_of(plain)
    assert sorted(rows_of(asked)) == sorted(rows_of(plain))


# --- accuracy on the fixture ------------------------------------------------------------------
def discovery_reads(client: Recording) -> dict[int, dict[str, str | None]]:
    """Return what the model read on each page in discovery (a retried window counts once)."""
    reads: dict[int, dict[str, str | None]] = {}
    page = 1
    last_images: list[bytes] | None = None
    start = 1
    for request, answer in client.log:
        if request.stage != "schema" or not isinstance(answer, WindowWithExtras):
            continue
        images = [p.png for p in request.parts if isinstance(p, Image)]
        if images == last_images:
            page = start  # the retry of the same window replaces the first answer
        start, last_images = page, images
        for entry in answer.pages:
            reads[page] = {e.name: (e.value or None) for e in entry.extras}
            page += 1
    return reads


def key_of(names: list[str], name: str) -> str:  # noqa: ARG001
    """Return the name a truth field has in the request (the request uses the truth's names)."""
    return name


def numbers(truth: dict[str, Any], tables: list[Table], client: Recording, pages: int) -> dict:
    """
    Count what the report of the spec asks for, for one run of one document.

    Only pages that hold a table are judged on the final values (``Table.extra_fields`` has no
    entry for a page without one); what the model read on any page is still counted in
    ``missed_before_the_region_check``.
    """
    names = [f["name"] for f in truth["fields"]]
    printed = {int(p): row for p, row in truth["printed"].items()}
    reads = discovery_reads(client)
    final = {page: row for table in tables for page, row in table.extra_fields.items()}
    pairs = [(p, n) for p, row in printed.items() for n in names if row[n] is not None]
    looks = sorted(r.page or 0 for r, _ in client.log if r.stage == "extras")
    return {
        "pages": pages,
        "missed_before_the_region_check": [
            (p, n) for p, n in pairs if reads.get(p, {}).get(key_of(names, n)) is None
        ],
        "missed_after_the_second_look": [
            (p, n) for p, n in pairs if p in final and final[p][key_of(names, n)].source_page != p
        ],
        "invented": [
            (p, n)
            for p, row in printed.items()
            for n in names
            if p in final and row[n] is None and final[p][key_of(names, n)].source_page == p
        ],
        "second_look_pages": looks,
        "false_alarm_pages": [p for p in looks if all(v is None for v in printed[p].values())],
        "second_looks_per_100_pages": round(100 * len(looks) / pages, 1),
    }


@pytest.mark.parametrize("run", RUNS)
@pytest.mark.parametrize("doc_id", EXTRA_IDS)
def test_the_values_the_carry_and_the_sources_equal_the_truth(doc_id, run):
    truth = load_doc(doc_id)["extra_fields"]
    pdf = DATA / f"{doc_id}.pdf"
    request = described_request(truth, pdf, carry=True)
    pages = pages_of(pdf)
    cache = CACHE / "fixture" / doc_id / f"run{run}"
    tables, client = run_pipeline_live(pdf, request, cache, pages * 4 + 20)

    found = numbers(truth, tables, client, pages)
    CACHE.mkdir(parents=True, exist_ok=True)
    (CACHE / f"report-{doc_id}-run{run}.json").write_text(json.dumps(found, indent=1))
    print(f"\nextra-fields {doc_id} run{run}: {found}")  # noqa: T201
    progress(
        f"  {doc_id} run{run}: missed {len(found['missed_after_the_second_look'])},"
        f" invented {len(found['invented'])}, second looks {found['second_look_pages']}"
    )

    if truth["expect_stale"] or truth["expect_blind"]:
        return  # a documented limit: reported above, not asserted
    names = [f["name"] for f in truth["fields"]]
    final = {page: row for table in tables for page, row in table.extra_fields.items()}
    for page, row in truth["expected"]["carry"].items():
        if int(page) not in final:
            continue  # a page with no table has no row to carry a value into
        for name in names:
            have = final[int(page)][key_of(names, name)]
            want = row[name]
            want_pair = None if want is None else (want["value"], want["source_page"])
            have_pair = None if have.source_page is None else (have.value, have.source_page)
            assert have_pair == want_pair, (doc_id, page, name)
    assert found["invented"] == []
    assert found["missed_after_the_second_look"] == []


# --- a slice of the real report ----------------------------------------------------------------
@pytest.mark.skipif(
    not (os.environ.get("QUOTABLE_LIVE_EXTRA_PDF") and os.environ.get("QUOTABLE_LIVE_EXTRA_LABEL")),
    reason="set QUOTABLE_LIVE_EXTRA_PDF and QUOTABLE_LIVE_EXTRA_LABEL for the real slice",
)
def test_a_slice_of_the_real_report_is_read_and_carried():
    source = os.environ.get("QUOTABLE_LIVE_EXTRA_PDF")
    label = os.environ.get("QUOTABLE_LIVE_EXTRA_LABEL")
    assert source and label  # the skipif above
    first = int(os.environ.get("QUOTABLE_LIVE_EXTRA_FIRST_PAGE", "1"))
    lines = int(os.environ.get("QUOTABLE_LIVE_EXTRA_LINES", "3"))
    box = tuple(
        float(x) for x in os.environ.get("QUOTABLE_LIVE_EXTRA_BOX", "0,0,260,130").split(",")
    )
    CACHE.mkdir(parents=True, exist_ok=True)
    pdf = CACHE / "real-slice.pdf"  # git-ignored with the rest of the cache
    with pymupdf.open(source) as whole, pymupdf.open() as part:
        part.insert_pdf(whole, from_page=first - 1, to_page=min(first + 59, whole.page_count) - 1)
        part.save(pdf)
        layers = {i + 1: load_layer(p) for i, p in enumerate(part)}
    starts = sorted(
        p
        for p, layer in layers.items()
        if find_candidates(layer, tokenize(label))
        and find_candidates(layer, tokenize(label))[0].status == "exact"
    )
    assert starts, "the label is on none of the pages of the slice"

    request = ExtraFields(neutral_fields(lines), carry_forward=True)
    header: set[str] = set()
    for page in starts:
        header |= words_in_box(pdf, page, box)
    assert overlap(header, request) == set(), "the request prints words of the real header"

    pages = len(layers)
    tables, client = run_pipeline_live(pdf, request, CACHE / "real", pages * 4 + 40)
    looks = sorted(r.page or 0 for r, _ in client.log if r.stage == "extras")
    final = {p: row for t in tables for p, row in t.extra_fields.items()}
    printing = sorted(
        p for p, row in final.items() if any(r.source_page == p for r in row.values())
    )
    report = {
        "pages": pages,
        "section_starts": starts,
        "pages_with_a_printed_value": printing,
        "missed": sorted(set(starts) - set(printing)),
        "invented": sorted(set(printing) - set(starts)),
        "second_look_pages": looks,
        "false_alarm_pages": sorted(set(looks) - set(starts)),
        "second_looks_per_100_pages": round(100 * len(looks) / pages, 1),
    }
    (CACHE / "report-real-slice.json").write_text(json.dumps(report, indent=1))
    print(f"\nextra-fields real slice: {report}")  # noqa: T201
    assert report["invented"] == []
    assert report["missed"] == []
