"""
The pipeline: text-layer check, table discovery, per-page extraction, grounding, position check.

0. Text-layer check: before anything is rendered or sent to a model, the PDF's text layer
   must be readable (see :mod:`quotable.text.quality`). If it is garbled or missing, the bad pages
   are OCR'd (see :mod:`quotable.ocr.pages`) and the merged layers are checked again; a layer
   that is still unreadable, or OCR that is off or not installed, raises ``TextLayerError``
   having made no request, because values could not be verified. There is no option to skip
   the check.
1. Table discovery: every page image goes to the model, ``discovery_pages`` at a time,
   and the model lists the tables on each page with their columns (multi-level headers
   are written ``<level1>.<level2>``). Tables with the same columns on different pages
   are one table (see :mod:`quotable.steps.discover`). Everything below runs once per table.
2. Page layouts: each page's columns come from its printed header (see
   :mod:`quotable.steps.layout`), so a column printed on some pages only is asked
   for only on those.
3. Page extraction (see :mod:`quotable.steps.extract`): one request per table and page (page
   image + columns) returns one object per row. On a page with several tables the request
   names the other tables and asks for this one only. Rows whose keys do not match are sent
   back once with the problems found; a second failure aborts the run.
4. Grounding and position check: every value is looked up in the table's text layer (the
   whole page, or on a page with several tables only that table's band, see
   :mod:`quotable.steps.layout`), then required to sit in its own row and column (see
   :mod:`quotable.steps.grounding` and :mod:`quotable.steps.position`).
5. Omission audit (``audit``, on by default; see :mod:`quotable.steps.audit`): a page whose text
   layer prints words that no extracted cell accounts for goes back to the model once, and the
   rows and cells it reports as omitted are kept only if the text layer confirms them. The
   table is grounded again if anything was kept.
6. Extra fields, merge and recheck, in that order (see :func:`run_pipeline`).
"""

import asyncio
import hashlib
import importlib.metadata
import logging
import math
import sys
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import pymupdf
from pydantic_ai.models import Model

from quotable.errors import CostLimitExceededError, TextLayerError
from quotable.estimate import cached_discovery_requests, estimate_discovery, estimate_rest
from quotable.llm.client import (
    CachedClient,
    LLMClient,
    PydanticAIClient,
    Request,
    model_name,
)
from quotable.llm.images import TODAY, ImagePolicy, check_page_sizes, policy_for
from quotable.meter import CostModel, RunMeter, dollars, make_error
from quotable.ocr.config import OcrConfig, OcrEngine
from quotable.ocr.paddle import PaddleEngine
from quotable.ocr.pages import ocr_pages
from quotable.progress import Reporter, choose_sink
from quotable.runs import RunInfo, write_run
from quotable.steps.audit import audit_table
from quotable.steps.discover import DISCOVERY_PAGES, Discovery, Found, discover
from quotable.steps.extra_fields import (
    ExtraField,
    ExtraFields,
    ExtraResult,
    find_suspects,
    flatten,
    ground_fields,
    propagate,
    second_look,
    table_bands,
    validate_extra_fields,
)
from quotable.steps.extract import DPI, extract_page, page_schema, render_page, render_png
from quotable.steps.layout import Header, find_header, page_layouts, shared_bands, table_layers
from quotable.steps.merge import merge_tables
from quotable.steps.recheck import recheck_fields, recheck_table
from quotable.storage import (
    DEFAULT_DIR_NAME,
    RUNS_DIR_NAME,
    CostLog,
    resolve_cache_dir,
    resolve_project_dir,
)
from quotable.table import PageResult, Table, ground_document
from quotable.text.layer import Layer, load_layer
from quotable.text.quality import (
    REMEDY_OCR_OFF,
    assess_text_layers,
    ocr_failed_message,
)

log = logging.getLogger("quotable")
MAX_CONCURRENT_REQUESTS = 4


Band = tuple[float, float]


@dataclass
class RunTrace:
    """What ``run_pipeline`` leaves for saving the run (spec 013): filled in when one is given."""

    layers: dict[int, Layer] = field(default_factory=dict)  # whole pages, after OCR
    # shared page -> (the table's cropped layer, its band), one per table on that page
    bands: dict[int, list[tuple[Layer, Band]]] = field(default_factory=dict)


@dataclass
class CostContext:
    """
    What turns on the cost limit, the estimates and the messages of spec 017 (internal).

    ``run_pipeline`` called without one behaves exactly as before. ``peek`` reads the request
    cache without asking; ``estimates`` collects what the final message compares with the cost.
    """

    meter: RunMeter
    reporter: Reporter
    cost_model: CostModel
    peek: Callable[[Request], Any]
    estimates: dict[str, Any] = field(default_factory=dict)
    pages: int = 0


def table_page_layers(
    found: list[Found], layers: dict[int, Layer], trace: RunTrace | None = None
) -> list[dict[int, Layer]]:
    """
    Return, per table, the text layer of each page it is on.

    A page with one table keeps the whole layer; on a page with several, each table gets
    its own band (``ExtractionError`` if one cannot be isolated), which ``trace`` also records.
    """
    out: list[dict[int, Layer]] = [{} for _ in found]
    for page in sorted({p for f in found for p in f.rows}):
        on_page = [i for i, f in enumerate(found) if page in f.rows]
        specs = [(found[i].label, *found[i].rows[page]) for i in on_page]
        cropped = table_layers(page, layers[page], specs)
        for i, layer in zip(on_page, cropped, strict=True):
            out[i][page] = layer
        if trace is not None and len(on_page) > 1:
            trace.bands[page] = list(
                zip(cropped, shared_bands(page, layers[page], specs), strict=True)
            )
    return out


def headers_and_bands(
    tables: Sequence[Table], trace: RunTrace
) -> tuple[list[dict[int, Header | None]], list[dict[int, Band]]]:
    """
    Return, per table, the header found on each whole page and its band on each shared page.

    A page that came from a merged-in part is searched with that part's own column names and
    the header's keys are renamed to the table's, by position.
    """
    headers: list[dict[int, Header | None]] = []
    bands: list[dict[int, Band]] = []
    for table in tables:
        part_of = {p: part for part in table.merged for p in part.pages}
        found: dict[int, Header | None] = {}
        mine: dict[int, Band] = {}
        for page in (r.page for r in table.pages):
            part = part_of.get(page)
            header = find_header(list(part.columns) if part else table.columns, trace.layers[page])
            if header is not None and part is not None:
                names = dict(zip(part.columns, table.columns, strict=True))
                header = replace(header, x={names[c]: x for c, x in header.x.items()})
            found[page] = header
            band = next(
                (b for lay, b in trace.bands.get(page, ()) if lay is table.layers[page]), None
            )
            if band is not None:
                mine[page] = band
        headers.append(found)
        bands.append(mine)
    return headers, bands


async def usable_layers(
    pdf: Path,
    layers: dict[int, Layer],
    engine: OcrEngine | None,
    config: OcrConfig,
    cache_dir: Path | None,
) -> tuple[dict[int, Layer], tuple[int, ...]]:
    """
    Return the text layers to ground against, and the pages whose layer came from OCR.

    A document that passes the check keeps its layers and the engine is never touched. One
    that fails has its bad pages (garbled or empty) OCR'd, in a worker thread, and the merged
    layers are checked again. ``TextLayerError`` (or its subclass ``OcrUnavailableError``) is
    raised if OCR is off, cannot run, or does not help; no model request has been made.
    """
    before = assess_text_layers(layers)
    if before.reason is None:
        return layers, ()
    if engine is None:
        raise TextLayerError(f"{before.reason} {REMEDY_OCR_OFF}")
    replaced = await asyncio.to_thread(
        ocr_pages, pdf, before.bad_pages, config, engine, resolve_cache_dir(cache_dir)
    )
    merged = {**layers, **replaced}
    after = assess_text_layers(merged)
    if after.reason is not None:
        describe = getattr(engine, "description", "OCR")
        raise TextLayerError(ocr_failed_message(before, after, before.bad_pages, describe))
    return merged, before.bad_pages


Printed = dict[int, dict[str, ExtraResult]]  # page -> field -> what the page prints


def printed_fields(
    extras: Mapping[int, Mapping[str, str | None]], layers: Mapping[int, Layer]
) -> Printed:
    """Ground what discovery read on each page; a field the page does not print is left out."""
    out: Printed = {}
    for page, values in extras.items():
        grounded = ground_fields(layers[page], values)
        out[page] = {
            name: ExtraResult(value, page, grounded[name])
            for name, value in values.items()
            if value is not None
        }
    return out


async def resolve_extra_fields(  # noqa: PLR0913, PLR0917
    extra_fields: ExtraFields,
    discovery: Discovery,
    layers: Mapping[int, Layer],
    pngs: Sequence[bytes],
    client: LLMClient,
    gate: asyncio.Semaphore,
    *,
    recheck: bool,
) -> tuple[Printed, dict[tuple[int, str], tuple[str, str]], int]:
    """
    Run the steps of requirement 13 up to the carry; return the pages' printed fields.

    Grounding, the recheck of fuzzy and ungrounded values, the missed-header check with its
    second look. Returns what each page prints, the accepted rechecks, and the number of suspect
    pages. The carry rule is applied by the caller (``propagate``). Every request waits for
    ``gate``, the run's one limit on requests in flight.
    """
    fields = {f.name: f for f, _ in flatten(extra_fields)}
    printed = printed_fields(discovery.extras, layers)
    changes: dict[tuple[int, str], tuple[str, str]] = {}
    if recheck:
        printed, changes = await recheck_fields(printed, layers, pngs, fields, client, gate)
    rows_by_page: dict[int, list[tuple[str, str]]] = {}
    for found in discovery.tables:
        for page, rows in found.rows.items():
            rows_by_page.setdefault(page, []).append(rows)
    bands = {p: table_bands(layers[p], rows) for p, rows in rows_by_page.items()}
    suspects = find_suspects(
        layers, {p: {n: r.grounding for n, r in row.items()} for p, row in printed.items()}, bands
    )

    async def look(page: int, evidence: dict[str, list[str]]) -> dict[str, ExtraResult]:
        asked: dict[str, ExtraField] = {name: fields[name] for name in evidence}
        async with gate:
            return await second_look(page, pngs[page - 1], layers[page], asked, evidence, client)

    answers = await asyncio.gather(*(look(p, ev) for p, ev in suspects.items()))
    for page, found_here in zip(suspects, answers, strict=True):
        printed.setdefault(page, {}).update(found_here)
    return printed, changes, len(suspects)


def attach_extra_fields(
    tables: list[Table],
    by_page: Mapping[int, Mapping[str, ExtraResult]],
    names: tuple[str, ...],
    changes: Mapping[tuple[int, str], tuple[str, str]],
) -> list[Table]:
    """Give each table the results of its own pages (a page two tables share goes to both)."""
    out = []
    for table in tables:
        mine = {r.page: dict(by_page[r.page]) for r in table.pages}
        used = {(r.source_page, n) for row in mine.values() for n, r in row.items()}
        kept = {key: value for key, value in changes.items() if key in used}
        out.append(replace(table, extra_fields=mine, extra_names=names, extra_changes=kept))
    return out


SAMPLE_PAGES = 3  # table pages the sample run covers: the first, the middle and the last


def choose_sample(jobs: Sequence[tuple[int, int]]) -> list[tuple[int, int]]:
    """
    Return the (table, page) jobs of the sample run, or none for a table too small to sample.

    Positions ``round(i * (T - 1) / 2)`` for i in 0, 1, 2 among the ``T`` jobs in (table, page)
    order, so a rerun chooses the same pages and finds their cached answers.
    """
    if len(jobs) <= SAMPLE_PAGES:
        return []
    last = SAMPLE_PAGES - 1
    return [jobs[round(i * (len(jobs) - 1) / last)] for i in range(SAMPLE_PAGES)]


async def _sample(
    costs: CostContext,
    jobs: Sequence[tuple[int, int]],
    tables: int,
    process: Callable[[frozenset[tuple[int, int]] | None], Awaitable[list[Table]]],
) -> None:
    """
    Run the whole process on a few table pages, then estimate the rest and check the limit.

    The sample's tables are thrown away; what it keeps is the cost it measured and the answers
    in the cache. A table of three pages or fewer is not sampled.
    """
    meter, reporter = costs.meter, costs.reporter
    picked = choose_sample(jobs)
    if not picked:
        meter.phase = "rest"
        reporter.phase("rest")
        reporter.fixed(
            f"quotable: discovery found {tables} tables on {len(jobs)} table pages; "
            "small enough to run as it is, no sample"
        )
        return
    meter.phase = "sample"
    reporter.phase("sample")
    reporter.announce_sample(tables, len(jobs), picked, meter.total)
    await process(frozenset(picked))
    estimate = estimate_rest(meter, len(jobs), len(picked))
    costs.estimates["rest"] = estimate
    meter.estimate_total = estimate.expected_total
    meter.phase = "rest"
    reporter.phase("rest")
    reporter.estimate_rest(estimate, meter.limit)
    if (
        meter.limit is not None
        and estimate.expected_total is not None
        and estimate.expected_total > meter.limit
    ):
        raise make_error(
            "estimate",
            limit=meter.limit,
            spent=meter.total,
            estimate=estimate.expected_total,
            stage=None,
        )


async def _estimate_discovery(
    pdf: Path,
    pngs: list[bytes],
    costs: CostContext,
    discovery_pages: int,
    extra_fields: ExtraFields | None,
) -> None:
    """Print the discovery estimate, stop if it is above the limit, and start the stage."""
    meter, reporter = costs.meter, costs.reporter
    meter.phase = "discovery"
    reporter.phase("discovery")
    with pymupdf.open(pdf) as document:
        sizes = [(page.rect.width, page.rect.height) for page in document]
    cached = await cached_discovery_requests(
        pngs, costs.peek, discovery_pages=discovery_pages, extra_fields=extra_fields
    )
    estimate = estimate_discovery(
        sizes,
        costs.cost_model,
        discovery_pages=discovery_pages,
        extra_fields=extra_fields,
        cached=cached,
    )
    costs.pages = len(sizes)
    costs.estimates["discovery"] = estimate
    reporter.estimate_discovery(estimate, discovery_pages, meter.limit)
    if meter.limit is not None and estimate.cost is not None and estimate.cost > meter.limit:
        raise make_error(
            "estimate",
            limit=meter.limit,
            spent=meter.total,
            estimate=estimate.cost,
            what="discovery",
        )
    meter.stage("schema", math.ceil(len(pngs) / discovery_pages))
    about = f"about {dollars(estimate.cost)}" if estimate.cost is not None else None
    reporter.start_stage("schema", about)


async def run_pipeline(  # noqa: PLR0913, PLR0915
    pdf: Path,
    client: LLMClient,
    *,
    discovery_pages: int = DISCOVERY_PAGES,
    recheck: bool = True,
    merge_reworded: bool = True,
    audit: bool = False,
    images: ImagePolicy = TODAY,
    ocr: OcrEngine | None = None,
    ocr_config: OcrConfig | None = None,
    cache_dir: Path | None = None,
    extra_fields: ExtraFields | None = None,
    trace: RunTrace | None = None,
    costs: CostContext | None = None,
) -> list[Table]:
    """
    Run the whole pipeline on one PDF with an already-built client (internal; tests use it).

    ``trace``, when given, is filled with the whole pages' layers and the shared pages' bands.

    ``audit`` (spec 014) runs the omission audit on every table after its first grounding.
    ``images`` (spec 014) is the resolution and detail of the page images that extraction, the
    audit and the recheck send; discovery and the extra-field stages always send ``pngs`` at 150
    dpi. A page too large for ``images`` raises ``ExtractionError`` before any request. Here,
    unlike in ``extract_tables``, ``audit`` is off by default and ``images`` is the pre-014
    policy, so the many callers that drive this function with scripted models keep their
    behavior; ``extract_tables`` passes its own defaults.

    ``extra_fields`` (spec 010) are checked first, before any request. In the order of the spec:
    discovery also reads the fields, they are grounded, fuzzy and ungrounded values are rechecked,
    pages that may hold a missed header get a second look, the carry rule runs, and the results
    are attached to the tables before the merge step.

    ``merge_reworded`` joins tables whose headers are worded differently on different pages
    when every check of spec 007 passes (``quotable.steps.merge``); it runs after extraction and
    before the recheck.

    ``ocr`` is the engine used for pages with a garbled or missing text layer (``None``: no
    OCR, such a document is rejected); ``ocr_config`` its settings; ``cache_dir`` where the
    OCR results are cached.

    ``costs`` (spec 017) turns on the run meter's phases, the estimates and the messages; without it
    nothing about the run changes.
    """
    if extra_fields is not None:
        validate_extra_fields(extra_fields)
    with pymupdf.open(pdf) as document:
        layers: dict[int, Layer] = {i + 1: load_layer(p) for i, p in enumerate(document)}
    # before rendering or any request; cannot be skipped
    layers, ocr_done = await usable_layers(pdf, layers, ocr, ocr_config or OcrConfig(), cache_dir)
    if trace is not None:
        trace.layers = layers
    check_page_sizes(pdf, images)  # before any render or request
    with pymupdf.open(pdf) as document:
        pngs = [render_png(p) for p in document]

    if costs is not None:
        await _estimate_discovery(pdf, pngs, costs, discovery_pages, extra_fields)
    discovery = await discover(
        pngs, client, discovery_pages=discovery_pages, extra_fields=extra_fields
    )
    if costs is not None:
        costs.reporter.end_stage()
    found = discovery.tables
    # may reject a page before extracting
    table_layers_by_page = table_page_layers(found, layers, trace)
    layouts = [
        page_layouts(f.columns, [layers[p] for p in f.pages]) for f in found
    ]  # from the whole pages: the header sits above a table's band

    gate = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)

    async def one(index: int, page: int, present: tuple[str, ...]) -> PageResult:
        table = found[index]
        others = [
            (f.label, f.columns) for i, f in enumerate(found) if i != index and page in f.rows
        ]
        async with gate:
            png = pngs[page - 1] if images.dpi == DPI else render_page(pdf, page, images.dpi)
            result = await extract_page(
                page, png, page_schema(table.schema, present), client, others, detail=images.detail
            )
        absent = tuple(c for c in table.columns if c not in present)
        rows = [{**dict.fromkeys(absent, ""), **row} for row in result.rows]
        return replace(result, rows=rows, absent=absent)

    all_jobs = [
        (index, page, layout.columns)
        for index, (f, lays) in enumerate(zip(found, layouts, strict=True))
        for page, layout in zip(f.pages, lays, strict=True)
    ]

    def stage(name: str, total: int, *, upper_bound: bool = False) -> None:
        if costs is not None:
            costs.meter.stage(name, total, upper_bound=upper_bound)
            costs.reporter.start_stage(name)

    def stage_done() -> None:
        if costs is not None:
            costs.reporter.end_stage()

    async def process(only: frozenset[tuple[int, int]] | None = None) -> list[Table]:
        """Run every stage after discovery on the (table, page) jobs in ``only`` (all if None)."""
        jobs = [j for j in all_jobs if only is None or (j[0], j[1]) in only]
        stage("extract", len(jobs))
        results = await asyncio.gather(*(one(*job) for job in jobs))
        stage_done()

        tables: list[Table] = []
        for index, f in enumerate(found):
            pages = [r for (i, _, _), r in zip(jobs, results, strict=True) if i == index]
            if not pages:
                continue
            kept = {r.page for r in pages}
            page_layers = table_layers_by_page[index]
            grounded, position = ground_document(f.columns, pages, page_layers)
            tables.append(
                Table(
                    f.columns,
                    pages,
                    page_layers,
                    grounded,
                    position,
                    [
                        lay
                        for page, lay in zip(f.pages, layouts[index], strict=True)
                        if page in kept
                    ],
                    label=f.label,
                    ocr_pages=tuple(r.page for r in pages if r.page in ocr_done),
                )
            )
        table_pages = sum(len(t.pages) for t in tables)
        if audit:
            stage("audit", table_pages, upper_bound=True)
            tables = list(
                await asyncio.gather(*(audit_table(t, pdf, client, images, gate) for t in tables))
            )
            stage_done()
            log.info(
                "audit: %d proposal(s), %d kept",
                sum(len(t.audit) for t in tables),
                sum(a.outcome == "accepted" for t in tables for a in t.audit),
            )
        if extra_fields is not None:
            tables = await extras_stage(tables, only, table_pages)
        if only is None and merge_reworded:  # the sample is not merged
            tables = merge_tables(tables)
        return await recheck_stage(tables, table_pages)

    async def recheck_stage(tables: list[Table], table_pages: int) -> list[Table]:
        if not recheck:
            return tables
        stage("recheck", table_pages, upper_bound=True)
        tables = list(
            await asyncio.gather(*(recheck_table(t, pdf, client, images, gate) for t in tables))
        )
        stage_done()
        return tables

    async def extras_stage(
        tables: list[Table], only: frozenset[tuple[int, int]] | None, table_pages: int
    ) -> list[Table]:
        assert extra_fields is not None
        scope = discovery
        if only is not None:  # the sample: only its pages, with every table that is on them
            pages = {page for _, page in only}
            scope = Discovery(
                [replace(f, rows={p: r for p, r in f.rows.items() if p in pages}) for f in found],
                {p: v for p, v in discovery.extras.items() if p in pages},
            )
            scope.tables = [f for f in scope.tables if f.rows]
        stage("extras", table_pages, upper_bound=True)
        printed, changes, suspect_pages = await resolve_extra_fields(
            extra_fields, scope, layers, pngs, client, gate, recheck=recheck
        )
        stage_done()
        if only is not None:
            return tables  # what the sample read is thrown away with it
        flat = flatten(extra_fields)
        by_page = propagate(sorted(layers), printed, flat, carry_forward=extra_fields.carry_forward)
        names = tuple(f.name for f, _ in flat)
        tables = attach_extra_fields(tables, by_page, names, changes)
        log.info(
            "extra fields: %d read on %d page(s); %d page(s) carry a value from an earlier page; "
            "%d suspect page(s) (second looks)",
            len(names),
            sum(1 for row in printed.values() if row),
            sum(
                1
                for page, row in by_page.items()
                if any(r.source_page not in (None, page) for r in row.values())
            ),
            suspect_pages,
        )
        return tables

    if costs is not None:
        await _sample(costs, [(i, page) for i, page, _ in all_jobs], len(found), process)
    return await process()


def _ocr_config(ocr: OcrConfig | bool) -> OcrConfig | None:  # noqa: FBT001
    """Return the OCR settings, or ``None`` when OCR is off."""
    if isinstance(ocr, OcrConfig):
        return ocr
    if isinstance(ocr, bool):
        return OcrConfig() if ocr else None
    msg = f"ocr must be True, False or an OcrConfig, not {type(ocr).__name__}"
    raise TypeError(msg)


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _save_run(  # noqa: PLR0913, PLR0917
    run_id: str,
    started: str,
    pdf: Path,
    model: Model | str,
    tables: list[Table],
    trace: RunTrace,
    **settings: Any,  # noqa: ANN401
) -> None:
    """Write the run to ``.quotable/runs/``; any failure is one line on stderr, never raised."""
    target = Path.cwd() / DEFAULT_DIR_NAME / RUNS_DIR_NAME
    try:
        project = resolve_project_dir()
        target = project / RUNS_DIR_NAME
        digest = hashlib.sha256()
        with pdf.open("rb") as handle:
            while chunk := handle.read(1 << 20):
                digest.update(chunk)
        with pymupdf.open(pdf) as document:
            sizes = {i + 1: (p.rect.width, p.rect.height) for i, p in enumerate(document)}
        pages = {r.page for t in tables for r in t.pages}
        headers, bands = headers_and_bands(tables, trace)
        info = RunInfo(
            id=run_id,
            started=started,
            ended=_now(),
            quotable=importlib.metadata.version("quotable"),
            model=model_name(model),
            name=pdf.name,
            path=str(pdf.resolve()),
            size=pdf.stat().st_size,
            sha256=digest.hexdigest(),
            pages=len(sizes),
            **settings,
        )
        write_run(
            project,
            info,
            tables,
            {p: trace.layers[p] for p in sorted(pages)},
            sizes,
            headers,
            bands,
        )
    except Exception as err:  # noqa: BLE001
        print(f"quotable: could not save the run to {target}: {err}", file=sys.stderr)


def _limit(max_cost: float | str | Decimal | None) -> Decimal | None:
    """Return the cost limit as dollars; ``ValueError`` if it is not a number above zero."""
    if max_cost is None:
        return None
    try:
        limit = Decimal(str(max_cost))
    except InvalidOperation:
        limit = Decimal("NaN")
    if not limit.is_finite() or limit <= 0:
        msg = f"max_cost must be a number of dollars above zero, not {max_cost!r}"
        raise ValueError(msg)
    return limit


async def run_metered(
    pdf: Path,
    client: LLMClient,
    costs: CostContext,
    **options: Any,  # noqa: ANN401
) -> list[Table]:
    """
    Run ``run_pipeline`` with a cost context; say how the run ended (internal).

    A run stopped by the cost limit waits for the requests already in flight, so the error shows
    what the provider will bill, then raises it. Any other failure only gets a closing message.
    """
    try:
        tables = await run_pipeline(pdf, client, costs=costs, **options)
    except CostLimitExceededError as err:
        if err.reason in ("spent", "unmetered"):
            await costs.meter.settled()
            err = costs.meter.error()  # noqa: PLW2901 (the same stop, with the settled numbers)
        costs.reporter.closing(err)
        raise err from None
    except Exception as err:
        costs.reporter.closing(err)
        raise
    costs.reporter.final(tables, costs.estimates, costs.pages)
    return tables


async def extract_tables_async(  # noqa: PLR0913
    pdf: str | Path,
    model: Model | str,
    *,
    cache_dir: str | Path | None = None,
    max_requests: int | None = None,
    model_settings: dict[str, Any] | None = None,
    discovery_pages: int = DISCOVERY_PAGES,
    recheck: bool = True,
    audit: bool = True,
    sharp_images: bool = True,
    ocr: OcrConfig | bool = True,
    merge_reworded: bool = True,
    extra_fields: ExtraFields | None = None,
    max_cost: float | str | Decimal | None = None,
    progress: bool = True,
) -> list[Table]:
    """
    Run the whole pipeline on one PDF; return one ``Table`` per table in it.

    ``model`` is required: a pydantic-ai ``"provider:model-name"`` string (the provider's API
    key comes from the environment, as pydantic-ai documents) or a pydantic-ai ``Model``
    instance. Model answers are always cached on disk, in ``cache_dir`` or else in
    ``.quotable/cache/`` in the current directory (``.quotable/`` is created if missing, with a
    ``.gitignore`` of its own);
    ``max_requests`` caps the new (uncached) requests and raises ``BudgetExceededError``
    beyond it. Each new request is recorded (tokens and price) in ``.quotable/cost/``, apart
    from the cache; ``quotable cost-report`` adds the records up.

    ``audit`` (default on, like ``recheck``) looks for rows and cells the model left out. Each
    page whose text layer prints words that no extracted cell accounts for (page numbers and
    titles count, but a word repeated on many pages of a table does not) goes back to the model
    once with its image, its rows and those words. A row or cell it reports is kept only if
    every value in it is found in the page's text layer, and is marked in ``Table.audit`` and in
    the ``audit_added`` column of ``records()``. Rows are numbered by position afterwards, so
    an added row shifts the rows after it. It costs up to one request per page; ``audit=False``
    turns it off.

    ``sharp_images`` (default on) renders the pages that extraction, the audit and the recheck
    send at 300 dpi instead of 150. For an OpenAI model they are sent with the highest image
    detail setting (``original``); for an Anthropic model, which has no such setting and shrinks
    large images itself, the 300-dpi page is sent as it is; any other provider keeps the 150-dpi
    image. A page whose image would be too large for the provider raises ``ExtractionError``
    before the first request. Verified to work with OpenAI only. ``False`` sends the images
    quotable sent before spec 014.

    ``ocr`` says what to do when the PDF's text layer is garbled or missing: ``True`` (the
    default) OCRs the bad pages with PaddleOCR using ``OcrConfig()``, an ``OcrConfig``
    configures that, and ``False`` rejects such a PDF with ``TextLayerError``. OCR results are
    cached next to the model answers. Either way the text layer is checked before any model
    request.

    ``merge_reworded`` (default on) joins two tables that are really one but whose column names
    are worded differently on different pages ("Requested Local Match" on some pages,
    "Requested Match" on others), when every check of ``quotable.steps.merge`` passes: the same
    column count, each name's words containing the other's, the same x positions, the same kind
    of value in every column, and exactly one possible partner. Any doubt leaves the tables
    apart. ``Table.merged`` lists what was joined; ``False`` turns the step off. It makes no
    model request.

    ``extra_fields`` (an ``ExtraFields``) names values to read from outside the tables, such as
    a page header. Each becomes a column on every row of every table, graded against the text
    layer like any other value, with the page that printed it in ``<name>__source_page``.
    Discovery reads them page by page; a page that prints a field uses it, and with
    ``carry_forward=True`` a page that does not takes the nearest earlier page's value.
    Pages that may hold a header the model missed get a second look. Without it nothing changes.

    ``max_cost`` (US dollars, above zero) limits what the call may cost. The total actual cost is
    checked after every request that reaches a model, and as soon as it is above the limit no
    further request is started: requests already sent finish and are billed, and
    ``CostLimitExceededError`` (a ``BudgetExceededError``) says what the call has cost, how far
    over the limit it is and how much to raise the limit by. Everything answered so far is cached,
    so a rerun with a higher limit pays nothing for it. The limit is separate from
    ``max_requests``. With a limit set, a model whose price is not known is refused before any
    request, and a request that reports no usage stops the run, because the cost could not be
    kept under the limit. ``progress`` (default on) prints the estimates and progress messages
    to standard error, or to the cell output in a notebook; ``False`` prints nothing and the
    limit still applies.

    Each call that returns also saves its run in ``.quotable/runs/<run id>/`` (same id as in
    the cost records); a failed save only prints a warning.
    """
    config = _ocr_config(ocr)
    limit = _limit(max_cost)
    directory = resolve_cache_dir(cache_dir)
    cost_log = CostLog()  # costs go to the project's .quotable/cost/, not into a named cache_dir
    meter = RunMeter(limit)
    reporter = Reporter(choose_sink(progress=progress), meter)
    cost_model = CostModel.for_model(model)
    if limit is not None and cost_model.price(1000, 100) is None:
        error = make_error(
            "unpriced", limit=limit, spent=Decimal(0), model=cost_model.name,
            cause=cost_model.why_unpriced,
        )  # fmt: skip
        reporter.closing(error)
        raise error

    def on_usage(request: Request, name: str, usage: Any, cost: Decimal | None) -> None:  # noqa: ANN401
        cost_log.record_usage(request, name, usage, cost)
        meter.add(request, usage, cost)

    client = CachedClient(
        PydanticAIClient(model, model_settings=model_settings, on_usage=on_usage),
        directory,
        max_requests,
        meter,
    )
    started = _now()
    trace = RunTrace()
    tables = await run_metered(
        Path(pdf),
        client,
        CostContext(meter, reporter, cost_model, client.peek),
        discovery_pages=discovery_pages,
        recheck=recheck,
        audit=audit,
        images=policy_for(model, sharp=sharp_images),
        merge_reworded=merge_reworded,
        extra_fields=extra_fields,
        ocr=None if config is None else PaddleEngine(config),
        ocr_config=config,
        cache_dir=directory,
        trace=trace,
    )
    _save_run(
        cost_log.run_id,
        started,
        Path(pdf),
        model,
        tables,
        trace,
        discovery_pages=discovery_pages,
        recheck=recheck,
        audit=audit,
        sharp_images=sharp_images,
        ocr=ocr,
        merge_reworded=merge_reworded,
        max_requests=max_requests,
        extra_fields=extra_fields,
    )
    return tables


def extract_tables(  # noqa: PLR0913
    pdf: str | Path,
    model: Model | str,
    *,
    cache_dir: str | Path | None = None,
    max_requests: int | None = None,
    model_settings: dict[str, Any] | None = None,
    discovery_pages: int = DISCOVERY_PAGES,
    recheck: bool = True,
    audit: bool = True,
    sharp_images: bool = True,
    ocr: OcrConfig | bool = True,
    merge_reworded: bool = True,
    extra_fields: ExtraFields | None = None,
    max_cost: float | str | Decimal | None = None,
    progress: bool = True,
) -> list[Table]:
    """Run the whole pipeline on one PDF (synchronous wrapper); one ``Table`` per table."""
    return asyncio.run(
        extract_tables_async(
            pdf,
            model,
            cache_dir=cache_dir,
            max_requests=max_requests,
            model_settings=model_settings,
            discovery_pages=discovery_pages,
            recheck=recheck,
            audit=audit,
            sharp_images=sharp_images,
            ocr=ocr,
            merge_reworded=merge_reworded,
            extra_fields=extra_fields,
            max_cost=max_cost,
            progress=progress,
        )
    )
