"""
Omission audit: rows and cells the first pass left out (spec 014).

Grounding checks the values the model gave. It cannot see a value the model left out: a whole
row, or a cell returned empty, leaves nothing to check. The text layer can still tell that
something is missing: words printed on the page (the table's layer, so the table's band on a page
that holds several tables) that no extracted cell accounts for. Each token of the layer is matched,
one for one, against the tokens of the table's cells; a word left over on many pages of one table
is page furniture (a running header) and does not count.

A page with such words goes back to the model once, with its image, its rows and those words as a
hint, and the model reports only what it omitted. A proposal is kept only if

* a row's position exists and the row is not a copy of a listed one, or a cell is empty in its
  listed row;
* every non-empty value is found in the table's text layer, exactly or in part (``fuzzy``: some
  of its words are missing, as when the layer splits a word over two lines or misreads a
  character), and a word of ``NEAR_MIN_LEN`` or more letters may be up to ``NEAR_EDITS`` letters
  off one page word (numbers must be exact). A value with no match at all is refused. The model's
  spelling is kept; a partly matched cell is flagged by the final grounding and the recheck then
  corrects it, as for any other flagged cell;
* it contains at least one of the unexplained words (a real omission has one, a repeat of
  something already extracted has none).

Nothing already extracted is ever changed. The page's rows are numbered by position afterwards.
Every proposal, kept or not, is reported in ``Table.audit``. The table is grounded again only if
something was kept.

The VRA script this was ported from keeps the old row numbers and numbers added rows after the
last one; quotable's row number is the row's position in the page everywhere, so it does not.
"""

import asyncio
import json
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path

from quotable.llm.answers import FilledCell, MissingRow, Omissions
from quotable.llm.client import Image, LLMClient, Request
from quotable.llm.images import ImagePolicy
from quotable.steps.extract import render_page
from quotable.steps.grounding import ground_rows
from quotable.steps.position import PageGrounding
from quotable.table import AuditItem, PageResult, Table, ground_document
from quotable.text.layer import Layer, tokenize

FURNITURE_SHARE = 0.3  # a word unexplained on this share of a table's pages ...
FURNITURE_MIN_PAGES = 5  # ... (tables with at least this many pages) is page furniture
HINT_MAX_WORDS = 40  # unexplained words listed in the request
CELL_HINT_MAX = 40  # empty cells named in the request
NEAR_EDITS = 2  # letters a proposed word may differ from a page word ...
NEAR_MIN_LEN = 5  # ... if it has this many letters; numbers must be exact
FOUND = ("exact", "fuzzy", "empty")  # grounding statuses a proposed value may have

AUDIT_PROMPT = (
    "You are checking an earlier extraction of the table on this page image. The "
    "rows it returned are listed after the image, numbered from 1 in the order "
    "given. It may have OMITTED something: (a) a whole data row that is printed on "
    "the page but missing from the list, or (b) a cell that is printed on the page "
    "but was returned as an empty string. Compare the list with the page image row "
    "by row and column by column, and report ONLY omissions.\n"
    "- missing_rows: for each row missing from the list, after_row (the number of "
    "the listed row it follows on the page; 0 if it comes before row 1) and values "
    "(every column in the column structure; an empty string for a cell that is "
    "empty on the page).\n"
    "- filled_cells: for each listed cell that is empty in the list but printed on "
    "the page: row (its number), column (the exact column name) and value.\n"
    "Transcribe values verbatim as printed: do not reformat numbers, currency or "
    "capitalisation, do not fix typos; a cell that wraps over several lines is ONE "
    "value joined with single spaces; rejoin words split with a hyphen at a line "
    "end; if a cell is visually shared by consecutive rows, repeat its value in "
    "each row it covers. Do not report a cell that is genuinely blank on the page. "
    "Do not change or correct any value that is already in the list. Do not report "
    "a row that is already in the list. Many pages have no omissions: if you find "
    "none, return empty lists."
)
POSITION_RULE = (
    " Every column in the column structure has a fixed place in every row, whether "
    "or not it has a value. Decide which column a value belongs to ONLY from its "
    "horizontal position on the page, under the column it is printed in - never "
    "from the order of the non-empty values in the row. An empty cell stays empty: "
    "do not move a value into a neighbouring column to fill it. When two narrow "
    "columns sit side by side and only one of them has a value, look at which of "
    "the two it is printed in."
)
HINT_TEXT = (
    "\n\nAn automatic check compared the page's machine-readable text layer with "
    "the listed cells. These words are printed on the page but appear in none of "
    "the listed cells (reading order): {words}\nThey may point to omitted rows or "
    "cells, or they may be page furniture or text-layer noise. The image is "
    "authoritative, and a word on this list is not by itself evidence of an "
    "omission."
)
CELL_HINT_TEXT = (
    "\n\nSome of those words sit inside cells that are EMPTY in the list (by their "
    "position on the page: listed row number, column, words):\n{cells}\nFor each, "
    "look at that cell in the image. If the image prints text there, report it "
    "under filled_cells with the value exactly as printed; if the cell is blank in "
    "the image, leave it out."
)


# --- unexplained words ----------------------------------------------------------------------
def unexplained(
    layer: Layer, rows: Sequence[dict[str, str]], names: Iterable[str]
) -> list[tuple[str, int]]:
    """Return (token, word id) of the layer's tokens that no cell accounts for, one for one."""
    names = list(names)
    remaining = Counter(t for row in rows for n in names for t in tokenize(row[n]))
    left = []
    for token, word in zip(layer.tokens, layer.tok_word, strict=True):
        if remaining[token] > 0:
            remaining[token] -= 1
        else:
            left.append((token, word))
    return left


def furniture(pages: Sequence[set[str]]) -> set[str]:
    """
    Return the tokens that are page furniture: unexplained on many pages of one table.

    ``pages`` holds each page's set of unexplained tokens. A table of fewer than
    ``FURNITURE_MIN_PAGES`` pages has none, since a header cannot be told from a row there.
    """
    if len(pages) < FURNITURE_MIN_PAGES:
        return set()
    seen: Counter[str] = Counter()
    for tokens in pages:
        seen.update(tokens)
    return {t for t, count in seen.items() if count >= FURNITURE_SHARE * len(pages)}


def audit_words(
    layer: Layer, rows: Sequence[dict[str, str]], names: Iterable[str], skip: set[str]
) -> tuple[list[str], set[str]]:
    """
    Return the page words no cell accounts for (in layer order, each word once), and their tokens.

    Words whose token is in ``skip`` (page furniture) are left out. The tokens are what a
    proposal must draw on.
    """
    ids: list[int] = []
    tokens: set[str] = set()
    for token, word in unexplained(layer, rows, names):
        if token in skip:
            continue
        tokens.add(token)
        if word not in ids:
            ids.append(word)
    return [layer.words[i].text for i in ids], tokens


# --- near spelling --------------------------------------------------------------------------
def within_edits(a: str, b: str, limit: int) -> bool:
    """
    Say whether ``a`` becomes ``b`` in ``limit`` edits or fewer (optimal string alignment).

    An edit is an insertion, a deletion, a substitution or a swap of two neighbouring letters.
    """
    if abs(len(a) - len(b)) > limit:
        return False
    older: list[int] = []
    previous = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        current = [i, *([0] * len(b))]
        for j, y in enumerate(b, 1):
            current[j] = min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (x != y))
            if i > 1 and j > 1 and x == b[j - 2] and a[i - 2] == y:
                current[j] = min(current[j], older[j - 2] + 1)
        older, previous = previous, current
    return previous[-1] <= limit


@dataclass
class AuditPage:
    """What judging the proposals for one page needs."""

    names: list[str]  # the columns the page prints
    layer: Layer
    evidence: set[str]  # tokens of the words no cell accounts for
    vocab: set[str] = field(init=False)  # every token the page prints

    def __post_init__(self) -> None:
        """Index the page's tokens for the near-spelling lookup."""
        self.vocab = set(self.layer.tokens)


def near_word(token: str, page: AuditPage) -> str:
    """Return the page's spelling of a near-miss ``token``, else ``token`` itself."""
    if token in page.vocab or len(token) < NEAR_MIN_LEN or any(ch.isdigit() for ch in token):
        return token
    near = {t for t in page.vocab if within_edits(token, t, NEAR_EDITS)}
    unexplained_near = near & page.evidence
    pick = unexplained_near if len(unexplained_near) == 1 else near
    return next(iter(pick)) if len(pick) == 1 else token  # ambiguous: no swap


def _spelled(value: str, page: AuditPage) -> str:
    return " ".join(near_word(t, page) for t in tokenize(value))


def _all_found(row: dict[str, str], page: AuditPage) -> bool:
    """Say whether every non-empty value of ``row`` is found, exactly or in part (near spelling)."""
    spelled = {k: _spelled(v, page) for k, v in row.items()}
    cells = ground_rows([spelled], page.names, page.layer)[0]
    return all(c.status in FOUND for c in cells.values())


def _draws_on(values: Iterable[str], page: AuditPage) -> bool:
    return any(t in page.evidence for v in values for t in tokenize(_spelled(v, page)))


def _is_copy(candidate: dict[str, str], rows: Sequence[dict[str, str]]) -> bool:
    """Say whether some row repeats every non-empty cell of ``candidate``."""
    filled = [k for k, v in candidate.items() if tokenize(v)]
    return bool(filled) and any(
        all(tokenize(candidate[k]) == tokenize(r.get(k, "")) for k in filled) for r in rows
    )


# --- judging --------------------------------------------------------------------------------
def judge_cell(
    fill: FilledCell, rows: Sequence[dict[str, str]], page: AuditPage, taken: set[tuple[int, str]]
) -> str:
    """Decide one proposed cell; ``rows`` are the listed rows and ``fill.row`` counts from 1."""
    if fill.column not in page.names or not 1 <= fill.row <= len(rows):
        return "invalid_cell"
    if not tokenize(fill.value):
        return "empty"
    if rows[fill.row - 1][fill.column].strip():
        return "not_empty"
    if (fill.row, fill.column) in taken:
        return "repeated"
    if not _all_found({**dict.fromkeys(page.names, ""), fill.column: fill.value}, page):
        return "ungrounded"
    return "accepted" if _draws_on([fill.value], page) else "no_evidence"


def judge_row(
    proposal: MissingRow, listed: int, rows: Sequence[dict[str, str]], page: AuditPage
) -> tuple[str, dict[str, str]]:
    """
    Decide one proposed row; return the outcome and the row (stripped, every column).

    ``listed`` is the number of rows the first pass returned (``after_row`` refers to them);
    ``rows`` are those and the rows accepted so far, for the copy check.
    """
    row = {n: proposal.values.get(n, "").strip() for n in page.names}
    if not 0 <= proposal.after_row <= listed or not any(tokenize(v) for v in row.values()):
        return "invalid_row", row
    if _is_copy(row, rows):
        return "duplicate", row
    if not _all_found(row, page):
        return "ungrounded", row
    return ("accepted" if _draws_on(row.values(), page) else "no_evidence"), row


Added = list[tuple[int, int, dict[str, str], AuditItem]]  # (after row, order given, row, item)


def _judge_all(
    result: PageResult, page: AuditPage, found: Omissions
) -> tuple[list[AuditItem], dict[tuple[int, str], str], list[tuple[int, AuditItem]], Added]:
    """Judge every proposal; return the items, the accepted fills and the accepted rows."""
    listed = [{k: r[k] for k in page.names} for r in result.rows]
    items: list[AuditItem] = []
    fills: dict[tuple[int, str], str] = {}
    filled: list[tuple[int, AuditItem]] = []
    for fill in found.filled_cells:
        outcome = judge_cell(fill, listed, page, set(fills))
        value = fill.value.strip()
        item = AuditItem(result.page, "cell", {fill.column: value}, outcome)
        items.append(item)
        if outcome == "accepted":
            fills[fill.row, fill.column] = value
            filled.append((fill.row, item))
    taken = list(listed)
    added: Added = []
    for k, proposal in enumerate(found.missing_rows):
        outcome, row = judge_row(proposal, len(listed), taken, page)
        item = AuditItem(result.page, "row", row, outcome)
        items.append(item)
        if outcome == "accepted":
            taken.append(row)
            added.append((proposal.after_row, k, row, item))
    added.sort(key=lambda t: t[:2])
    return items, fills, filled, added


def apply(
    result: PageResult, page: AuditPage, found: Omissions
) -> tuple[PageResult, list[AuditItem]]:
    """
    Judge the model's proposals for one page and apply the accepted ones.

    Accepted cells are filled in their listed rows, then accepted rows are inserted after the
    listed row each names (0: first), in the order the model gave them. The page's rows are then
    numbered by position; each accepted item gets its number in ``AuditItem.row``. Returns
    ``result`` itself when nothing was accepted, and an item for every proposal.
    """
    items, fills, filled, added = _judge_all(result, page, found)
    if not fills and not added:
        return result, items
    blank = dict.fromkeys(result.absent, "")
    rows: list[dict[str, str]] = []

    def push(row: dict[str, str]) -> int:
        rows.append(row)
        return len(rows)

    for _, _, row, item in (t for t in added if t[0] == 0):
        item.row = push({**blank, **row})
    for number, original in enumerate(result.rows, 1):
        mine = dict(original)
        here = push(mine)
        for (r, column), value in fills.items():
            if r == number:
                mine[column] = value
        for r, item in filled:
            if r == number:
                item.row = here
        for after, _, row, item in added:
            if after == number:
                item.row = push({**blank, **row})
    return replace(result, rows=rows), items


# --- the request ----------------------------------------------------------------------------
def hints(page: PageGrounding, names: Sequence[str]) -> list[str]:
    """
    Name the empty cells whose area on the page prints words, with those words (at most 40).

    The area is the row's window and the column's range from the position check. Placement is by
    position, not by token: a page-wide token count cannot tell which copy of a repeated word is
    the one left over. Columns without a fitted range are skipped.
    """
    found: dict[tuple[int, str], list[str]] = {}
    for word in page.layer.words:
        x, y = (word.bbox[0] + word.bbox[2]) / 2, (word.bbox[1] + word.bbox[3]) / 2
        row = next((r for r, (lo, hi) in page.row_windows.items() if lo <= y <= hi), None)
        column = next(
            (
                n
                for n in names
                if n in page.column_ranges
                and page.column_ranges[n][0] <= x < page.column_ranges[n][1]
            ),
            None,
        )
        if row is None or column is None or page.rows[row][column].strip():
            continue
        found.setdefault((row, column), []).append(word.text)
    ordered = sorted(found.items(), key=lambda kv: (kv[0][0], list(names).index(kv[0][1])))
    return [f"Row {row + 1}, {column}: {' '.join(w)}" for (row, column), w in ordered][
        :CELL_HINT_MAX
    ]


def numbered_structure(names: Sequence[str]) -> str:
    """Return the column structure with each column's place and the column count."""
    # shortcut: names only, without the descriptions discovery gave (a Table keeps just the
    # names); keep them on the Table and send them if the model files values in wrong columns

    lines = "\n".join(f"{i}. {n}" for i, n in enumerate(names, 1))
    return f"Column structure ({len(names)} columns, left to right):\n{lines}"


def build_request(  # noqa: PLR0913, PLR0917
    page: int,
    png: bytes,
    images: ImagePolicy,
    names: Sequence[str],
    rows: Sequence[dict[str, str]],
    words: Sequence[str],
    cells: Sequence[str],
) -> Request:
    """Build the audit request of one page; ``rows`` hold only the columns the page prints."""
    listing = "\n".join(
        f"Row {i}: {json.dumps(r, ensure_ascii=False)}" for i, r in enumerate(rows, 1)
    )
    text = "Rows returned by the earlier extraction:\n" + listing
    text += HINT_TEXT.format(words=" ".join(words[:HINT_MAX_WORDS]))
    if cells:
        text += CELL_HINT_TEXT.format(cells="\n".join(cells[:CELL_HINT_MAX]))
    parts = [numbered_structure(names), Image(png, images.detail), text]
    return Request("audit", AUDIT_PROMPT + POSITION_RULE, Omissions, parts, page)


# --- the step -------------------------------------------------------------------------------
async def audit_table(
    table: Table, pdf: Path, client: LLMClient, images: ImagePolicy, gate: asyncio.Semaphore
) -> Table:
    """
    Ask the model about each page of ``table`` with unexplained words; keep what is confirmed.

    Needs the table grounded (the row windows and column ranges name the empty cells). Returns
    ``table`` itself when no page needed a request; a table whose proposals were all rejected
    keeps its rows and grounding and gains the items in ``audit``.
    """
    names = {r.page: [c for c in table.columns if c not in r.absent] for r in table.pages}
    layer = table.layers
    skip = furniture(
        [{t for t, _ in unexplained(layer[r.page], r.rows, names[r.page])} for r in table.pages]
    )

    async def one(result: PageResult) -> tuple[PageResult, list[AuditItem]]:
        mine = names[result.page]
        words, evidence = audit_words(layer[result.page], result.rows, mine, skip)
        if not words:
            return result, []
        page = AuditPage(mine, layer[result.page], evidence)
        listed = [{k: r[k] for k in mine} for r in result.rows]
        cells = hints(table.grounded[result.page], mine)
        async with gate:
            png = render_page(pdf, result.page, images.dpi)
            found = await client.ask(
                build_request(result.page, png, images, mine, listed, words, cells)
            )
        return apply(result, page, found)

    done = await asyncio.gather(*(one(r) for r in table.pages))
    items = [item for _, page_items in done for item in page_items]
    if not items:
        return table
    pages = [result for result, _ in done]
    if all(new is old for new, old in zip(pages, table.pages, strict=True)):
        return replace(table, audit=[*table.audit, *items])
    grounded, position = ground_document(table.columns, pages, table.layers)
    return replace(
        table, pages=pages, grounded=grounded, position=position, audit=[*table.audit, *items]
    )
