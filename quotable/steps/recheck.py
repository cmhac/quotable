"""
Recheck: a second look at the cells that grounding flagged.

Grounding flags cells whose value is not (exactly) in the page's text layer, but does
not correct them. Each page with such cells goes back to the model once: the page
image, its previous rows, the page's whole text layer (one visual line per line), and
the flagged cells with the reason for each flag. The model is told that the text layer
is the reference and to copy its reading, so text-layer errors can pass into the
output; it keeps its own value only when the text layer has no text for the cell. The
answers are applied, the whole document is grounded again, and an answer is kept
only if grounding of that cell got strictly better (by ``SEVERITY``); the rest keep
their original value, flagged as before. Blank answers and answers that tokenize
like the original are never applied.

Deliberately left out (see the original project): splitting pages with many flagged
cells over several requests, capping the size of the text layer sent, and undoing
accepted changes that make some other cell worse.
"""

import asyncio
import json
from collections.abc import Mapping, Sequence
from dataclasses import replace
from pathlib import Path

import pymupdf

from quotable.llm.answers import ExtrasRecheck, PageRecheck
from quotable.llm.client import Image, LLMClient, Request
from quotable.steps.extra_fields import ExtraField, ExtraResult, ground_fields
from quotable.steps.extract import render_png
from quotable.steps.grounding import SEVERITY
from quotable.table import PageResult, Proposal, Table, ground_document
from quotable.text.layer import Layer, tokenize

RECHECK_STATUSES = ("fuzzy", "misplaced", "incomplete", "ungrounded")
RECHECK_PROMPT = (
    "You previously extracted the table on this page image. An automatic check "
    "compared every value you returned with the PDF's text layer, which is an OCR "
    "of this same page, and some cells did not match. The whole text layer of the "
    "page is given, one visual line per line; the columns of a table row appear on "
    "the same line.\n"
    "The text layer is the reference. For EACH listed cell, find that cell's text "
    "in the text layer (same row, same column) and return it copied character for "
    "character, with its spelling, digits and punctuation. A disagreement in "
    "spelling or characters is NOT a reason to keep your own value: the text layer "
    "is more reliable than your reading of the image, especially for unusual names. "
    "Keep your own value only when the text layer has no text for that cell (it is "
    "missing, or belongs to another cell). A cell that wraps over several lines is "
    "one value joined with single spaces. Use an empty string if the cell is empty. "
    "Do not explain."
)
RECHECK_REASONS = {
    "fuzzy": "only a partial match was found in the text layer",
    "ungrounded": "no match was found anywhere in the text layer",
    "misplaced": "the text was found, but not in this row and column",
    "incomplete": "the text layer of this cell has words your value lacks",
}

Key = tuple[int, int, str]  # (page, 1-based row, column)


def _rank(status: str) -> int:
    return SEVERITY.get(status, 0)


def _request(table: Table, page: int, png: bytes) -> Request:
    flagged = [
        f
        for f in table.flagged()
        if f.page == page and f.status in RECHECK_STATUSES and not f.extra
    ]
    rows = table.grounded[page].rows
    listing = "\n".join(
        f'- row {f.row}, column "{f.column}": previously "{rows[f.row - 1][f.column]}" '
        f"({RECHECK_REASONS[f.status]})"
        for f in flagged
    )
    previous = json.dumps([{"row": i, **row} for i, row in enumerate(rows, 1)], ensure_ascii=False)
    text_layer = "\n".join(table.layers[page].lines())
    parts = [
        Image(png),
        f"Previous rows:\n{previous}",
        f"Text layer of the whole page, one visual line per line:\n{text_layer}",
        f"Cells to re-check:\n{listing}",
    ]
    return Request("recheck", RECHECK_PROMPT, PageRecheck, parts, page)


def _apply(pages: list[PageResult], changes: dict[Key, str]) -> list[PageResult]:
    """Return the pages with ``changes`` applied; untouched pages are shared."""
    out = []
    for result in pages:
        edits = {(r, c): v for (p, r, c), v in changes.items() if p == result.page}
        rows = [dict(r) for r in result.rows]
        for (row, column), value in edits.items():
            rows[row - 1][column] = value
        out.append(replace(result, rows=rows) if edits else result)
    return out


def _regrounded(table: Table, changes: dict[Key, str]) -> Table:
    pages = _apply(table.pages, changes)
    grounded, position = ground_document(table.columns, pages, table.layers)
    return replace(table, pages=pages, grounded=grounded, position=position)


def _proposals(table: Table, answers: dict[int, PageRecheck]) -> list[Proposal]:
    """Turn the model's answers into proposals; answers for unlisted cells are dropped."""
    flagged = {
        (f.page, f.row, f.column): f.status
        for f in table.flagged()
        if f.status in RECHECK_STATUSES and not f.extra
    }
    out = []
    for page, answer in answers.items():
        for cell in answer.cells:
            key = (page, cell.row, cell.column)
            if key not in flagged:
                continue
            original = table.grounded[page].rows[cell.row - 1][cell.column]
            if cell.value == original:
                continue  # unchanged: no proposal
            proposal = Proposal(page, cell.row, cell.column, original, cell.value, flagged[key])
            if not cell.value.strip():
                proposal.outcome = "blank_ignored"
            elif tokenize(cell.value) == tokenize(original):
                proposal.outcome = "same_tokens"
            out.append(proposal)
    return out


async def recheck_table(table: Table, pdf: Path, client: LLMClient) -> Table:
    """Ask the model about each page's flagged cells; keep the answers that ground better."""
    pages = sorted(
        {f.page for f in table.flagged() if f.status in RECHECK_STATUSES and not f.extra}
    )
    if not pages:
        return table
    with pymupdf.open(pdf) as document:
        pngs = {n: render_png(document[n - 1]) for n in pages}
    answers = await asyncio.gather(*(client.ask(_request(table, n, pngs[n])) for n in pages))
    proposals = _proposals(table, dict(zip(pages, answers, strict=True)))

    trial = [p for p in proposals if not p.outcome]
    if trial:
        attempt = _regrounded(table, {(p.page, p.row, p.column): p.proposed for p in trial})
        for p in trial:
            after = attempt.grounded[p.page].cells[p.row - 1][p.column].status
            p.status_after = after
            p.outcome = "accepted" if _rank(after) < _rank(p.status_before) else "not_improved"
    accepted = {(p.page, p.row, p.column): p.proposed for p in proposals if p.outcome == "accepted"}
    final = _regrounded(table, accepted) if accepted else table
    return replace(final, proposals=proposals)


EXTRAS_RECHECK_PROMPT = (
    "You previously read some fields printed on this page, outside its tables (a page header or "
    "caption). An automatic check compared every value you returned with the PDF's text layer, "
    "which is an OCR of this same page, and the listed ones did not match. The whole text layer "
    "of the page is given, one visual line per line.\n"
    "The text layer is the reference. For EACH listed field, find its text in the text layer and "
    "return it copied character for character, with its spelling, digits and punctuation. A "
    "disagreement in spelling or characters is NOT a reason to keep your own value: the text "
    "layer is more reliable than your reading of the image. Keep your own value only when the "
    "text layer has no text for that field. A value that wraps over several lines is one value "
    "joined with single spaces. Do not explain."
)
EXTRA_RECHECK_STATUSES = ("fuzzy", "ungrounded")

FieldKey = tuple[int, str]  # (the page that printed the value, the field's name)


async def recheck_fields(
    printed: Mapping[int, Mapping[str, ExtraResult]],
    layers: Mapping[int, Layer],
    pngs: Sequence[bytes],
    fields: Mapping[str, ExtraField],
    client: LLMClient,
) -> tuple[dict[int, dict[str, ExtraResult]], dict[FieldKey, tuple[str, str]]]:
    """
    Give each printing page's fuzzy or ungrounded field values one second look.

    One request per page that has such values: the page image, its whole text layer and the
    flagged fields; the model is told the text layer is the reference. An answer is kept only if
    that field then grounds strictly better (by ``SEVERITY``); a blank answer, or one that
    tokenizes like the original, is never applied. Returns the printed results after the
    changes and the accepted changes, ``(page, field) -> (original, new)``.
    """
    flagged = {
        page: {n: r for n, r in row.items() if r.grounding.status in EXTRA_RECHECK_STATUSES}
        for page, row in printed.items()
    }
    pages = sorted(page for page, row in flagged.items() if row)
    result = {page: dict(row) for page, row in printed.items()}
    if not pages:
        return result, {}

    def request(page: int) -> Request:
        listing = "\n".join(
            f'- {name}: {fields[name].description}; previously "{r.value}" '
            f"({RECHECK_REASONS[r.grounding.status]})"
            for name, r in flagged[page].items()
        )
        parts = [
            Image(pngs[page - 1]),
            "Text layer of the whole page, one visual line per line:\n"
            + "\n".join(layers[page].lines()),
            f"Fields to re-check:\n{listing}",
        ]
        return Request("recheck", EXTRAS_RECHECK_PROMPT, ExtrasRecheck, parts, page)

    answers = await asyncio.gather(*(client.ask(request(p)) for p in pages))
    changes: dict[FieldKey, tuple[str, str]] = {}
    for page, answer in zip(pages, answers, strict=True):
        proposed = {
            e.name: e.value
            for e in answer.extras
            if e.name in flagged[page]
            and e.value is not None
            and e.value.strip()
            and tokenize(e.value) != tokenize(flagged[page][e.name].value)
        }
        if not proposed:
            continue
        trial = {n: proposed.get(n, r.value) for n, r in printed[page].items()}
        grounded = ground_fields(layers[page], trial)
        for name, new in proposed.items():
            before = flagged[page][name]
            if _rank(grounded[name].status) < _rank(before.grounding.status):
                result[page][name] = ExtraResult(new, page, grounded[name])
                changes[page, name] = (before.value, new)
    return result, changes
