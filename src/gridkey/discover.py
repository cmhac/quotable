"""
Table discovery: which tables the document holds, and which pages each one is on.

The pages are shown to the model in windows of ``discovery_pages`` consecutive pages,
one window after another. Each answer lists the tables on each page (columns, plus the
words of the table's first and last data row on that page). Tables with the same column
names on different pages are one table.

Windows after the first are also told the tables found so far. A page may continue a
table without printing its header again; asked about such a page alone, the model
invents columns, so it is told to reuse the known column names for a page that
continues a known table and never to invent columns for a header it cannot see.

Deliberately left out: merging tables whose column names drift between pages beyond
case and punctuation (``gridkey.merge`` does that after extraction, from independent
evidence), and any use of the text layer to find tables.
"""

import json
from dataclasses import dataclass, field

from gridkey.llm import Image, LLMClient, Request
from gridkey.models import Column, PageTables, TableInfo, TableSchema, WindowTables
from gridkey.schema import ExtractionError, validate_schema
from gridkey.text import tokenize

DISCOVERY_PAGES = 4  # how many consecutive pages go in one discovery request
DISCOVER_PROMPT = (
    "These are the pages of a PDF report, in order. List EVERY distinct table printed on each "
    "page, top to bottom. A table is a block of data laid out in columns under its own column "
    "header; a page can hold one table or several (for example a small summary table above a "
    "long detail table). Do not merge two tables that have different columns, and do not split "
    "one table into several. For each table give its columns (multi-level headers as "
    "'<level1>.<level2>'; header text wrapped over lines is joined with single spaces), and the "
    "words printed on its first and last data rows on that page, in reading order, separated by "
    "single spaces - copy only printed words: no separators and no placeholders for empty "
    "cells. A total or subtotal row that belongs to the table counts as its last row. Ignore "
    "page titles, page numbers and section captions that are not table rows. Do not extract the "
    "data rows. A page with no table has an empty list. Answer for every page, in page order."
)
CARRY_PROMPT = (
    " Tables already found on earlier pages of this PDF are listed after the images. A page may "
    "continue one of them WITHOUT printing its column header again - then report that table "
    "with exactly the same column names as listed. Never invent columns for a table whose "
    "header you cannot see: either it continues a known table (reuse its columns) or its header "
    "is printed on the page you are looking at. A new table with its own header is reported "
    "with the columns printed in that header."
)


class PageCountError(ValueError):
    """The answer does not have one entry per page of the window."""


@dataclass
class Found:
    """One table as discovery found it: its columns, and where it is on each page."""

    label: str
    schema: TableSchema
    rows: dict[int, tuple[str, str]] = field(default_factory=dict)  # page -> first, last row

    @property
    def columns(self) -> list[str]:
        """Return the column names."""
        return [c.name.strip() for c in self.schema.columns]

    @property
    def pages(self) -> list[int]:
        """Return the pages the table is on, in order."""
        return sorted(self.rows)

    def add(self, page: int, info: TableInfo) -> None:
        """
        Record the table's first and last row on ``page``.

        If the page already has this table (the model listed it twice, e.g. in two
        pieces), the first row of the first piece and the last row of the last piece
        are kept, so the table covers both.
        """
        if page in self.rows:
            self.rows[page] = (self.rows[page][0], info.last_row)
        else:
            self.rows[page] = (info.first_row, info.last_row)


def signature(names: list[str]) -> tuple[str, ...]:
    """Return the column names as comparison tokens: case and punctuation do not matter."""
    return tuple(" ".join(tokenize(n)) for n in names)


def match_pages(answer: WindowTables, pages: list[int]) -> list[PageTables]:
    """Return the answer's entries, matched to ``pages`` by order."""
    if len(answer.pages) != len(pages):
        msg = f"expected one entry per page image ({len(pages)}), got {len(answer.pages)}"
        raise PageCountError(msg)
    return list(answer.pages)


def merge(found: list[Found], page: int, tables: list[TableInfo]) -> None:
    """Add the tables reported for ``page`` to the ones found so far."""
    for info in tables:
        sig = signature([c.name for c in info.columns])
        known = next((f for f in found if signature(f.columns) == sig), None)
        if known is None:
            columns = [Column(name=c.name, description=c.description) for c in info.columns]
            known = Found(info.label, TableSchema(columns=columns))
            found.append(known)
        known.add(page, info)


def validate_found(found: list[Found]) -> None:
    """Raise ``ExtractionError`` if there is no table or a table's columns are unusable."""
    if not found:
        msg = "table discovery found no table in the document"
        raise ExtractionError(msg)
    for table in found:
        validate_schema(table.schema)


def known_tables(found: list[Found]) -> str:
    """Return the prompt text that lists the tables found so far."""
    lines = [
        f"- table {i}: pages {f.pages}; columns: {json.dumps(f.columns, ensure_ascii=False)}"
        for i, f in enumerate(found, 1)
    ]
    return "Known tables:\n" + "\n".join(lines)


def _retry_text(answer: WindowTables, problem: str) -> str:
    previous = answer.model_dump_json()
    return (
        f"Your previous answer was invalid:\n- {problem}\n\nPrevious output:\n{previous}\n\n"
        "Return the corrected answer, with one entry per page image."
    )


async def _ask_window(
    images: list[bytes], pages: list[int], found: list[Found], client: LLMClient
) -> list[PageTables]:
    """Ask about one window; repeat once if the answer does not cover every page."""
    prompt = DISCOVER_PROMPT + (CARRY_PROMPT if found else "")
    parts: list[str | Image] = [Image(images[p - 1]) for p in pages]
    if found:
        parts.append(known_tables(found))
    answer = await client.ask(Request("schema", prompt, WindowTables, parts))
    try:
        return match_pages(answer, pages)
    except PageCountError as err:
        retry = [*parts, _retry_text(answer, str(err))]
        answer = await client.ask(Request("schema", prompt, WindowTables, retry))
        try:
            return match_pages(answer, pages)
        except PageCountError as again:
            msg = (
                f"pages {pages[0]}-{pages[-1]}: discovery answer still invalid after one "
                f"retry: {again}"
            )
            raise ExtractionError(msg) from again


async def discover(
    images: list[bytes], client: LLMClient, *, discovery_pages: int = DISCOVERY_PAGES
) -> list[Found]:
    """Return every table in the document, in order of first appearance."""
    if discovery_pages < 1:
        msg = f"discovery_pages must be at least 1, got {discovery_pages}"
        raise ValueError(msg)
    found: list[Found] = []
    for start in range(0, len(images), discovery_pages):
        pages = list(range(start + 1, min(start + discovery_pages, len(images)) + 1))
        for page, entry in zip(pages, await _ask_window(images, pages, found, client), strict=True):
            merge(found, page, entry.tables)
    validate_found(found)
    return found
