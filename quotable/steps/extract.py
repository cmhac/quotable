"""
Per-page extraction: one request per (table, page) returns one object per row.

The request carries the page image and the table's columns; on a page that holds several tables
it also names the other tables and asks for this one only. Rows whose keys do not match are sent
back once with the problems found; a second failure raises ``ExtractionError``. No grounding
happens here (see :mod:`quotable.steps.grounding`).
"""

import json

import pymupdf

from quotable.errors import ExtractionError
from quotable.llm.answers import PageRows, TableSchema
from quotable.llm.client import Image, LLMClient, Request
from quotable.table import PageResult

DPI = 150
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
