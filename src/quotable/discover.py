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
case and punctuation (``quotable.merge`` does that after extraction, from independent
evidence), and any use of the text layer to find tables.
"""

import json
from dataclasses import dataclass, field

from quotable.extra_fields import ExtraFields, extras_prompt, flatten
from quotable.llm import Image, LLMClient, Request
from quotable.models import (
    Column,
    PageTables,
    TableInfo,
    TableSchema,
    WindowTables,
    WindowWithExtras,
)
from quotable.schema import ExtractionError, validate_schema
from quotable.text import tokenize

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


@dataclass
class Discovery:
    """What discovery found: the tables, and (with extra fields) each page's field values."""

    tables: list[Found]
    extras: dict[int, dict[str, str | None]] = field(default_factory=dict)  # page -> name -> value


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


def _retry_text(answer: WindowTables, problems: list[str]) -> str:
    previous = answer.model_dump_json()
    listed = "\n- ".join(problems)
    return (
        f"Your previous answer was invalid:\n- {listed}\n\nPrevious output:\n{previous}\n\n"
        "Return the corrected answer, with one entry per page image."
    )


def answer_problems(answer: WindowTables, pages: list[int], names: list[str] | None) -> list[str]:
    """Return what is wrong with a window answer: the page count, and the extra-field names."""
    problems: list[str] = []
    try:
        match_pages(answer, pages)
    except PageCountError as err:
        problems.append(str(err))
    if names is not None:
        for page, entry in zip(pages, answer.pages, strict=False):
            got = [e.name for e in getattr(entry, "extras", [])]
            if sorted(got) != sorted(names):
                problems.append(
                    f"page {page}: expected the extra fields {names}, each exactly once; got {got}"
                )
    return problems


def extras_of(entry: PageTables) -> dict[str, str | None]:
    """Return a page's field values; an empty string counts as not printed."""
    values = getattr(entry, "extras", [])
    return {e.name: (e.value if e.value is not None and e.value.strip() else None) for e in values}


async def _ask_window(
    images: list[bytes],
    pages: list[int],
    found: list[Found],
    client: LLMClient,
    extra_fields: ExtraFields | None = None,
) -> list[PageTables]:
    """Ask about one window; repeat once if the answer does not cover every page."""
    prompt = DISCOVER_PROMPT + (CARRY_PROMPT if found else "")
    output: type[WindowTables] = WindowTables
    names: list[str] | None = None
    if extra_fields is not None:
        prompt += "\n\n" + extras_prompt(extra_fields)
        output = WindowWithExtras
        names = [f.name for f, _ in flatten(extra_fields)]
    parts: list[str | Image] = [Image(images[p - 1]) for p in pages]
    if found:
        parts.append(known_tables(found))
    answer = await client.ask(Request("schema", prompt, output, parts))
    problems = answer_problems(answer, pages, names)
    if not problems:
        return list(answer.pages)
    retry = [*parts, _retry_text(answer, problems)]
    answer = await client.ask(Request("schema", prompt, output, retry))
    problems = answer_problems(answer, pages, names)
    if problems:
        msg = (
            f"pages {pages[0]}-{pages[-1]}: discovery answer still invalid after one "
            f"retry: {'; '.join(problems)}"
        )
        raise ExtractionError(msg)
    return list(answer.pages)


async def discover(
    images: list[bytes],
    client: LLMClient,
    *,
    discovery_pages: int = DISCOVERY_PAGES,
    extra_fields: ExtraFields | None = None,
) -> Discovery:
    """
    Return every table in the document, in order of first appearance.

    With ``extra_fields`` the same requests also ask for those fields on each page, and
    ``Discovery.extras`` holds the answers by page; without them the requests are unchanged.
    """
    if discovery_pages < 1:
        msg = f"discovery_pages must be at least 1, got {discovery_pages}"
        raise ValueError(msg)
    found: list[Found] = []
    extras: dict[int, dict[str, str | None]] = {}
    for start in range(0, len(images), discovery_pages):
        pages = list(range(start + 1, min(start + discovery_pages, len(images)) + 1))
        entries = await _ask_window(images, pages, found, client, extra_fields)
        for page, entry in zip(pages, entries, strict=True):
            merge(found, page, entry.tables)
            if extra_fields is not None:
                extras[page] = extras_of(entry)
    validate_found(found)
    return Discovery(found, extras)
