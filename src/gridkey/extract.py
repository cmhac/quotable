"""
The pipeline: text-layer check, table discovery, per-page extraction, grounding, position check.

0. Text-layer check: before anything is rendered or sent to a model, the PDF's text layer
   must be readable (see :mod:`gridkey.textcheck`). If it is garbled or missing, the bad pages
   are OCR'd (see :mod:`gridkey.ocr_pages`) and the merged layers are checked again; a layer
   that is still unreadable, or OCR that is off or not installed, raises ``TextLayerError``
   having made no request, because values could not be verified. There is no option to skip
   the check.
1. Table discovery: every page image goes to the model, ``discovery_pages`` at a time,
   and the model lists the tables on each page with their columns (multi-level headers
   are written ``<level1>.<level2>``). Tables with the same columns on different pages
   are one table (see :mod:`gridkey.discover`). Everything below runs once per table.
2. Page layouts: each page's columns come from its printed header (see
   :mod:`gridkey.layout`), so a column printed on some pages only is asked
   for only on those.
3. Page extraction: one request per table and page (page image + columns) returns one
   object per row. On a page with several tables the request names the other tables and
   asks for this one only. Rows whose keys do not match are sent back once with the
   problems found; a second failure aborts the run.
4. Grounding and position check: every value is looked up in the table's text layer (the
   whole page, or on a page with several tables only that table's band, see
   :mod:`gridkey.regions`), then required to sit in its own row and column (see
   ``grounding`` and ``position``).
"""

import asyncio
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pymupdf
from pydantic_ai.models import Model

from gridkey._model import PydanticAIClient
from gridkey._paddle import PaddleEngine
from gridkey.cache import resolve_cache_dir
from gridkey.discover import DISCOVERY_PAGES, Found, discover
from gridkey.layout import page_layouts
from gridkey.llm import CachedClient, Image, LLMClient, Request
from gridkey.merge import merge_tables
from gridkey.models import PageRows, TableSchema
from gridkey.ocr import OcrConfig, OcrEngine
from gridkey.ocr_pages import ocr_pages
from gridkey.recheck import recheck_table
from gridkey.regions import table_layers
from gridkey.schema import ExtractionError
from gridkey.table import PageResult, Table, ground_document
from gridkey.text import Layer, load_layer
from gridkey.textcheck import REMEDY_OCR_OFF, TextLayerError, assess_text_layers, ocr_failed_message

DPI = 150
MAX_CONCURRENT_REQUESTS = 4
MAX_PROBLEMS = 30
MAX_PREVIOUS_OUTPUT_CHARS = 20_000  # truncation of the output echoed on retry

EXTRACT_PROMPT = (
    "Extract every data row of the table on this page image. Return one JSON "
    "object per row. Each object must have EXACTLY the keys listed in the "
    "column structure (same spelling, no extra keys, none missing), and every "
    "value must be a string. Transcribe values verbatim as printed - do not "
    "reformat numbers, currency or capitalisation, do not fix typos. A cell "
    "that wraps over several lines is ONE value: join the lines with a single "
    "space; if a word is split with a hyphen at a line end, rejoin it into the "
    "whole word. Use an empty string for an empty cell. Skip header rows, page "
    "titles and page numbers. Include total/subtotal rows only if they are "
    "table rows. If a cell is visually shared by consecutive rows (blank "
    "below it), repeat its value in each row it covers."
)
MULTI_TABLE_SENTENCE = (
    "This page holds more than one table. Extract ONLY the table whose columns are listed in "
    "the column structure; do not return rows of the other table(s) named below."
)


def validate_rows(rows: list[dict[str, str]], keys: list[str]) -> list[str]:
    """Return what is wrong with the rows' keys (empty if nothing)."""
    problems = []
    for i, row in enumerate(rows, 1):
        missing = [k for k in keys if k not in row]
        extra = [k for k in row if k not in keys]
        if missing:
            problems.append(f"row {i}: missing keys {missing}")
        if extra:
            problems.append(f"row {i}: unexpected keys {extra}")
    return problems[:MAX_PROBLEMS]


def column_structure(schema: TableSchema) -> str:
    """Return the schema as the prompt text that lists the columns."""
    lines = "\n".join(f"- {c.name.strip()}: {c.description}" for c in schema.columns)
    return f"Column structure (left to right):\n{lines}"


def retry_prompt(rows: list[dict[str, str]], problems: list[str]) -> str:
    """Return the text that sends invalid rows back with what was wrong."""
    previous = json.dumps(rows, ensure_ascii=False)[:MAX_PREVIOUS_OUTPUT_CHARS]
    return (
        "Your previous answer was invalid:\n"
        + "\n".join(f"- {p}" for p in problems)
        + f"\n\nPrevious output:\n{previous}\n\nReturn the corrected rows for this page."
    )


def render_png(page: pymupdf.Page) -> bytes:
    """Render a page to PNG bytes at ``DPI`` (honours the page's rotation)."""
    return page.get_pixmap(dpi=DPI).tobytes("png")


def page_schema(schema: TableSchema, present: tuple[str, ...]) -> TableSchema:
    """Return the schema restricted to the columns a page prints."""
    keep = set(present)
    columns = [c for c in schema.columns if c.name.strip() in keep]
    return TableSchema(columns=columns, notes=schema.notes)


def other_tables_text(others: list[tuple[str, list[str]]]) -> str:
    """Return the prompt text that names the other tables on the page."""
    lines = "\n".join(f"- {label}: {', '.join(columns)}" for label, columns in others)
    return f"Other tables on this page:\n{lines}"


async def extract_page(
    page: int,
    png: bytes,
    schema: TableSchema,
    client: LLMClient,
    others: list[tuple[str, list[str]]] | None = None,
) -> PageResult:
    """
    Extract one table's rows from one page; retry once with the problems named if invalid.

    ``others`` names (label, columns) of the other tables on the page, if there are any.
    """
    keys = [c.name.strip() for c in schema.columns]
    base: list[str | Image] = [column_structure(schema), Image(png)]
    prompt = EXTRACT_PROMPT
    if others:
        base.append(other_tables_text(others))
        prompt = f"{EXTRACT_PROMPT} {MULTI_TABLE_SENTENCE}"
    answer = await client.ask(Request("extract", prompt, PageRows, base, page))
    problems = validate_rows(answer.rows, keys)
    if not problems:
        return PageResult(page, answer.rows)
    retry = [*base, retry_prompt(answer.rows, problems)]
    answer = await client.ask(Request("extract", prompt, PageRows, retry, page))
    problems = validate_rows(answer.rows, keys)
    if problems:
        msg = f"page {page}: rows still invalid after one retry: {problems}"
        raise ExtractionError(msg)
    return PageResult(page, answer.rows)


def table_page_layers(found: list[Found], layers: dict[int, Layer]) -> list[dict[int, Layer]]:
    """
    Return, per table, the text layer of each page it is on.

    A page with one table keeps the whole layer; on a page with several, each table gets
    its own band (``ExtractionError`` if one cannot be isolated).
    """
    out: list[dict[int, Layer]] = [{} for _ in found]
    for page in sorted({p for f in found for p in f.rows}):
        on_page = [i for i, f in enumerate(found) if page in f.rows]
        specs = [(found[i].label, *found[i].rows[page]) for i in on_page]
        for i, layer in zip(on_page, table_layers(page, layers[page], specs), strict=True):
            out[i][page] = layer
    return out


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


async def run_pipeline(  # noqa: PLR0913
    pdf: Path,
    client: LLMClient,
    *,
    discovery_pages: int = DISCOVERY_PAGES,
    recheck: bool = True,
    merge_reworded: bool = True,
    ocr: OcrEngine | None = None,
    ocr_config: OcrConfig | None = None,
    cache_dir: Path | None = None,
) -> list[Table]:
    """
    Run the whole pipeline on one PDF with an already-built client (internal; tests use it).

    ``merge_reworded`` joins tables whose headers are worded differently on different pages
    when every check of spec 007 passes (``gridkey.merge``); it runs after extraction and
    before the recheck.

    ``ocr`` is the engine used for pages with a garbled or missing text layer (``None``: no
    OCR, such a document is rejected); ``ocr_config`` its settings; ``cache_dir`` where the
    OCR results are cached.
    """
    with pymupdf.open(pdf) as document:
        layers: dict[int, Layer] = {i + 1: load_layer(p) for i, p in enumerate(document)}
    # before rendering or any request; cannot be skipped
    layers, ocr_done = await usable_layers(pdf, layers, ocr, ocr_config or OcrConfig(), cache_dir)
    with pymupdf.open(pdf) as document:
        pngs = [render_png(p) for p in document]

    found = await discover(pngs, client, discovery_pages=discovery_pages)
    table_layers_by_page = table_page_layers(found, layers)  # may reject a page before extracting
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
            result = await extract_page(
                page, pngs[page - 1], page_schema(table.schema, present), client, others
            )
        absent = tuple(c for c in table.columns if c not in present)
        rows = [{**dict.fromkeys(absent, ""), **row} for row in result.rows]
        return replace(result, rows=rows, absent=absent)

    jobs = [
        (index, page, layout.columns)
        for index, (f, lays) in enumerate(zip(found, layouts, strict=True))
        for page, layout in zip(f.pages, lays, strict=True)
    ]
    results = await asyncio.gather(*(one(*job) for job in jobs))

    tables: list[Table] = []
    for index, f in enumerate(found):
        pages = [r for (i, _, _), r in zip(jobs, results, strict=True) if i == index]
        page_layers = table_layers_by_page[index]
        grounded, position = ground_document(f.columns, pages, page_layers)
        tables.append(
            Table(
                f.columns,
                pages,
                page_layers,
                grounded,
                position,
                layouts[index],
                label=f.label,
                ocr_pages=tuple(r.page for r in pages if r.page in ocr_done),
            )
        )
    if merge_reworded:
        tables = merge_tables(tables)
    if recheck:
        tables = list(await asyncio.gather(*(recheck_table(t, pdf, client) for t in tables)))
    return tables


def _ocr_config(ocr: OcrConfig | bool) -> OcrConfig | None:  # noqa: FBT001
    """Return the OCR settings, or ``None`` when OCR is off."""
    if isinstance(ocr, OcrConfig):
        return ocr
    if isinstance(ocr, bool):
        return OcrConfig() if ocr else None
    msg = f"ocr must be True, False or an OcrConfig, not {type(ocr).__name__}"
    raise TypeError(msg)


async def extract_tables_async(  # noqa: PLR0913
    pdf: str | Path,
    model: Model | str,
    *,
    cache_dir: str | Path | None = None,
    max_requests: int | None = None,
    model_settings: dict[str, Any] | None = None,
    discovery_pages: int = DISCOVERY_PAGES,
    recheck: bool = True,
    ocr: OcrConfig | bool = True,
    merge_reworded: bool = True,
) -> list[Table]:
    """
    Run the whole pipeline on one PDF; return one ``Table`` per table in it.

    ``model`` is required: a pydantic-ai ``"provider:model-name"`` string (the provider's API
    key comes from the environment, as pydantic-ai documents) or a pydantic-ai ``Model``
    instance. Model answers are always cached on disk, in ``cache_dir`` or else in ``.gridkey/``
    in the current directory (created if missing, with a ``.gitignore`` of its own);
    ``max_requests`` caps the new (uncached) requests and raises ``BudgetExceededError``
    beyond it.

    ``ocr`` says what to do when the PDF's text layer is garbled or missing: ``True`` (the
    default) OCRs the bad pages with PaddleOCR using ``OcrConfig()``, an ``OcrConfig``
    configures that, and ``False`` rejects such a PDF with ``TextLayerError``. OCR results are
    cached next to the model answers. Either way the text layer is checked before any model
    request.

    ``merge_reworded`` (default on) joins two tables that are really one but whose column names
    are worded differently on different pages ("Requested Local Match" on some pages,
    "Requested Match" on others), when every check of ``gridkey.merge`` passes: the same
    column count, each name's words containing the other's, the same x positions, the same kind
    of value in every column, and exactly one possible partner. Any doubt leaves the tables
    apart. ``Table.merged`` lists what was joined; ``False`` turns the step off. It makes no
    model request.
    """
    config = _ocr_config(ocr)
    directory = resolve_cache_dir(cache_dir)
    client = CachedClient(
        PydanticAIClient(model, model_settings=model_settings), directory, max_requests
    )
    return await run_pipeline(
        Path(pdf),
        client,
        discovery_pages=discovery_pages,
        recheck=recheck,
        merge_reworded=merge_reworded,
        ocr=None if config is None else PaddleEngine(config),
        ocr_config=config,
        cache_dir=directory,
    )


def extract_tables(  # noqa: PLR0913
    pdf: str | Path,
    model: Model | str,
    *,
    cache_dir: str | Path | None = None,
    max_requests: int | None = None,
    model_settings: dict[str, Any] | None = None,
    discovery_pages: int = DISCOVERY_PAGES,
    recheck: bool = True,
    ocr: OcrConfig | bool = True,
    merge_reworded: bool = True,
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
            ocr=ocr,
            merge_reworded=merge_reworded,
        )
    )
