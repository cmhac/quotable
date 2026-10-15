"""
The pipeline: text-layer check, schema discovery, per-page extraction, grounding, position check.

0. Text-layer check: before anything is rendered or sent to a model, the PDF's text layer
   must be readable (see :mod:`pdf_table_extract.textcheck`). A garbled or missing layer
   raises ``TextLayerError`` having made no request, because values could not be verified.
   There is no option to skip this.
1. Schema discovery: the first ``schema_pages`` page images go to the model in one
   request, which returns only the column structure (multi-level headers are
   written ``<level1>.<level2>``).
2. Page layouts: each page's columns come from its printed header (see
   :mod:`pdf_table_extract.layout`), so a column printed on some pages only is asked
   for only on those.
3. Page extraction: one request per page (page image + columns) returns one object
   per row. Rows whose keys do not match are sent back once with the problems found;
   a second failure aborts the run.
4. Grounding and position check: every value is looked up in the page's text layer,
   then required to sit in its own row and column (see ``grounding`` and ``position``).
"""

import asyncio
import json
from dataclasses import replace
from pathlib import Path

import pymupdf

from pdf_table_extract.layout import page_layouts
from pdf_table_extract.llm import Image, LLMClient, Request
from pdf_table_extract.models import PageRows, TableSchema
from pdf_table_extract.recheck import recheck_table
from pdf_table_extract.table import PageResult, Table, ground_document
from pdf_table_extract.text import Layer, load_layer
from pdf_table_extract.textcheck import check_text_layers

DPI = 150
SCHEMA_PAGES = 5  # how many leading pages are shown to schema discovery
MAX_CONCURRENT_REQUESTS = 4
MAX_PROBLEMS = 30
MAX_PREVIOUS_OUTPUT_CHARS = 20_000  # truncation of the output echoed on retry

SCHEMA_PROMPT = (
    "These are the first pages of a PDF containing a table. Determine ONLY the "
    "column structure of the table - do not extract any row data. Return the "
    "columns in left-to-right order. If a header has multiple levels (a "
    "spanning header over sub-headers), name the column '<level1>.<level2>' "
    "(and deeper levels the same way). If header text is wrapped across lines, "
    "join it with a single space. Ignore page titles, subtitles and page "
    "numbers. Report a column only once even though it repeats on each page."
)
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


class ExtractionError(RuntimeError):
    """The model output could not be turned into a valid table."""


def validate_schema(schema: TableSchema) -> list[str]:
    """Return the column names, raising if they cannot key a table."""
    names = [c.name.strip() for c in schema.columns]
    problems = []
    if not names:
        problems.append("no columns")
    if any(not n for n in names):
        problems.append("blank column name")
    if len(set(names)) != len(names):
        problems.append("duplicate column names")
    if problems:
        msg = f"schema discovery returned an unusable schema: {', '.join(problems)}"
        raise ExtractionError(msg)
    return names


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


async def extract_page(page: int, png: bytes, schema: TableSchema, client: LLMClient) -> PageResult:
    """Extract one page's rows; retry once with the problems named if invalid."""
    keys = [c.name.strip() for c in schema.columns]
    base = [column_structure(schema), Image(png)]
    answer = await client.ask(Request("extract", EXTRACT_PROMPT, PageRows, base, page))
    problems = validate_rows(answer.rows, keys)
    if not problems:
        return PageResult(page, answer.rows)
    retry = [*base, retry_prompt(answer.rows, problems)]
    answer = await client.ask(Request("extract", EXTRACT_PROMPT, PageRows, retry, page))
    problems = validate_rows(answer.rows, keys)
    if problems:
        msg = f"page {page}: rows still invalid after one retry: {problems}"
        raise ExtractionError(msg)
    return PageResult(page, answer.rows)


async def extract_table_async(
    pdf: Path,
    client: LLMClient,
    *,
    schema_pages: int = SCHEMA_PAGES,
    recheck: bool = True,
) -> Table:
    """Run the whole pipeline on one PDF."""
    with pymupdf.open(pdf) as document:
        layers: dict[int, Layer] = {i + 1: load_layer(p) for i, p in enumerate(document)}
        check_text_layers(layers)  # before rendering or any request; cannot be skipped
        pngs = [render_png(p) for p in document]

    schema_request = Request(
        "schema", SCHEMA_PROMPT, TableSchema, [Image(png) for png in pngs[:schema_pages]]
    )
    schema = await client.ask(schema_request)
    columns = validate_schema(schema)
    layouts = page_layouts(columns, [layers[n] for n in sorted(layers)])

    gate = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)

    async def one(number: int, png: bytes, present: tuple[str, ...]) -> PageResult:
        async with gate:
            result = await extract_page(number, png, page_schema(schema, present), client)
        absent = tuple(c for c in columns if c not in present)
        rows = [{**dict.fromkeys(absent, ""), **row} for row in result.rows]
        return replace(result, rows=rows, absent=absent)

    pages = await asyncio.gather(
        *(
            one(n, png, lay.columns)
            for n, (png, lay) in enumerate(zip(pngs, layouts, strict=True), 1)
        )
    )
    grounded, position = ground_document(columns, list(pages), layers)
    table = Table(columns, list(pages), layers, grounded, position, layouts)
    if recheck:
        table = await recheck_table(table, pdf, client)
    return table


def extract_table(
    pdf: Path,
    client: LLMClient,
    *,
    schema_pages: int = SCHEMA_PAGES,
    recheck: bool = True,
) -> Table:
    """Run the whole pipeline on one PDF (synchronous wrapper)."""
    return asyncio.run(
        extract_table_async(Path(pdf), client, schema_pages=schema_pages, recheck=recheck)
    )
