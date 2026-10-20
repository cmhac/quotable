"""
The browsing API of the review app (spec 013 task 007, requirements B3, B5 and C1 to C6).

Every number and fact the runs list, run, table and cell screens show is computed here from the
stored run (:mod:`quotable.runs`), the verdicts and drafts (:mod:`quotable.review.verdicts`),
the cost log and the PDF (:mod:`quotable.review.sources`); the browser only draws. Nothing here
writes to the project folder. A table is addressed by its ``index`` (0-based, as stored and as the
queue and verdicts use it); ``number`` is ``index + 1``, the "Table N" people see.

A table's columns are the page, the row, the PDF's columns and the extra fields. Each has a
``key`` that sorts and filters use: the library's own names (``output_names``, so a PDF column
called ``page`` makes the library's ``page_``) and, for an extra field, the name of its value
column. A cell is identified in URLs by its ``name`` (the PDF column or the extra field) and the
row's page and number, with ``extra/`` before an extra field's name.

The cells a filter selects for "Cell n of N" are those of the matching rows (in the sort order)
whose status is chosen, whose column is the chosen one and, with ``flagged``, that need review.
"""

import csv
import io
import re
from bisect import bisect_left
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

from quotable.review import sources
from quotable.review.queue import FLAGGED, QueueSettings, population, review_state
from quotable.review.routing import BadRequest, NotFound, Raw, Request, Route
from quotable.review.verdicts import CellKey, ExtraKey, Key, Verdict
from quotable.runs import Run, RunCell, RunRow, RunSummary, RunTable, list_runs
from quotable.steps.grounding import SEVERITY, UNFLAGGED
from quotable.table import OutputNames, output_names

PAGE_SIZE = 100
STATUS_ORDER = (
    "exact",
    "fuzzy",
    "misplaced",
    "ungrounded",
    "untokenized",
    "empty",
    "not_on_page",
)
EXPLANATIONS = {
    "exact": "Every word of the value is on the page, in its row and column.",
    "fuzzy": "The value is on the page with small differences; compare it with the matched text.",
    "misplaced": "The words are on the page, but not in this cell's row and column.",
    "ungrounded": "The value's words are not on the page.",
    "untokenized": (
        "The value has no words or numbers to look up (only symbols), so it could not be checked."
    ),
    "empty": "The model left this cell blank.",
    "not_on_page": "This page does not print this column.",
}
REVIEWS = ("any", "unreviewed", "correct", "changed", "unsure", "note")
_VERDICT_ORDER = ("stale", "changed", "unsure", "correct")
_MAIN_LABEL = {
    "changed": "✎ Changed",
    "unsure": "? Can't tell",
    "correct": "✓ Correct",
    "none": "Not reviewed",
}
_NUMBER = re.compile(r"[-+]?(?:[0-9]+\.?[0-9]*|\.[0-9]+)")
_NOT_FOUND = RunCell("empty", None, None, 0, None, None, [])


# --- small helpers -----------------------------------------------------------------------------
def _one(query: Mapping[str, list[str]], name: str) -> str | None:
    values = query.get(name)
    return values[-1] if values else None


def _flag(query: Mapping[str, list[str]], name: str) -> bool:
    text = _one(query, name)
    if text in (None, "", "0", "false"):
        return False
    if text in ("1", "true"):
        return True
    msg = f"{name} must be 0 or 1"
    raise BadRequest(msg)


def _int(query: Mapping[str, list[str]], name: str, minimum: int) -> int | None:
    text = _one(query, name)
    if text in (None, ""):
        return None
    if not re.fullmatch(r"[0-9]+", text) or int(text) < minimum:
        msg = f"{name} must be a whole number of at least {minimum}"
        raise BadRequest(msg)
    return int(text)


def _number(text: str) -> float | None:
    """Return ``text`` as a number after removing ``,`` ``$`` ``%`` and brackets, else ``None``."""
    cleaned = re.sub(r"[,$%()\[\]{}]", "", text.strip())
    return float(cleaned) if _NUMBER.fullmatch(cleaned) else None


def _pages_text(pages: Sequence[int]) -> str:
    """Return ``p. 5``, ``pp. 4–5`` or ``pp. 1–3, 5``."""
    ranges: list[list[int]] = []
    for page in sorted(set(pages)):
        if ranges and page == ranges[-1][1] + 1:
            ranges[-1][1] = page
        else:
            ranges.append([page, page])
    text = ", ".join(str(a) if a == b else f"{a}–{b}" for a, b in ranges)
    return ("pp. " if len(set(pages)) > 1 else "p. ") + text


def _digits(text: str, what: str) -> int:
    if not re.fullmatch(r"[0-9]+", text):
        raise NotFound(f"no such {what}")
    return int(text)


def _table_at(run: Run, text: str) -> tuple[int, RunTable]:
    index = _digits(text, "table")
    if index >= len(run.tables):
        raise NotFound("no such table")
    return index, run.tables[index]


# --- one table, ready to filter ----------------------------------------------------------------
@dataclass
class _Cell:
    key: str
    name: str
    extra: bool
    value: str
    status: str
    coverage: float | None
    source_page: int | None
    verdict_key: Key | None
    state: str = "none"  # none | stale | correct | changed | unsure
    was: str | None = None  # what a stale verdict judged
    note: bool = False


@dataclass
class _Row:
    page: int
    row: int
    cells: list[_Cell]
    status: str
    recheck: bool
    ocr: bool
    merged: bool
    review: dict[str, Any]
    src: RunRow


@dataclass
class _Ctx:
    run: Run
    table: RunTable
    names: OutputNames
    rows: list[_Row]
    index: dict[str, int]  # key -> position in a row's cells
    numeric: dict[str, bool]
    by_position: dict[tuple[int, int], _Row]
    latest: Mapping[Key, Verdict]
    drafts: Mapping[Key, Any]
    extra_changes: dict[tuple[int, str], tuple[str, str]]
    ocr_pages: set[int]


def _review(cells: list[_Cell], *, ocr: bool, merged: bool) -> dict[str, Any]:
    states = {c.state for c in cells}
    state = next((s for s in _VERDICT_ORDER if s in states), "none")
    stale = next((c for c in cells if c.state == "stale"), None)
    unreviewed = sum(1 for c in cells if c.status not in UNFLAGGED and c.state in ("none", "stale"))
    note = any(c.note for c in cells)
    was = stale.was if stale is not None else None
    label = [f"Stale · was {was}" if state == "stale" else _MAIN_LABEL[state]]
    if state != "none" and unreviewed:
        label.append(f"· {unreviewed} not reviewed")
    if note:
        label.append("· note")
    if ocr:
        label.append("· OCR page")
    if merged:
        label.append("· merged part")
    return {
        "state": state,
        "was": was if state == "stale" else None,
        "unreviewed": unreviewed,
        "note": note,
        "ocr": ocr,
        "merged": merged,
        "label": " ".join(label),
    }


def _judge(cell: _Cell, latest: Mapping[Key, Verdict], drafts: Mapping[Key, Any]) -> None:
    if cell.verdict_key is None:
        return
    found = latest.get(cell.verdict_key)
    if found is not None:
        cell.note = bool(found.note)
        if found.extracted == cell.value:
            cell.state = found.verdict
        else:
            cell.state, cell.was = "stale", found.extracted
    draft = drafts.get(cell.verdict_key)
    if draft is not None and draft.note:
        cell.note = True


def _build(project: Path, run: Run, table: RunTable) -> _Ctx:  # noqa: PLR0914
    verdicts, draft_store = sources.stores(project)
    latest = verdicts.latest()
    drafts = draft_store.all()
    sha = run.summary.sha256
    columns = tuple(table.columns)
    names = output_names(table.columns, table.extra_names)
    accepted = {(p["page"], p["row"]) for p in table.proposals if p["outcome"] == "accepted"}
    extra_changes = {(c[0], c[1]): (c[2], c[3]) for c in table.extra_changes}
    ocr_pages = set(table.ocr_pages)
    merged_pages = {p for part in table.merged for p in part["pages"]}
    rows: list[_Row] = []
    for src in table.rows:
        cells = [
            _Cell(
                column,
                column,
                False,
                src.values.get(column, ""),
                (found := src.cells.get(column, _NOT_FOUND)).status,
                found.coverage,
                None,
                CellKey(sha, columns, src.page, src.row, column),
            )
            for column in table.columns
        ]
        printed = table.extra_fields.get(src.page, {})
        for name in table.extra_names:
            got = printed.get(name)
            source = None if got is None else got.source_page
            cells.append(
                _Cell(
                    names.fields[name],
                    name,
                    True,
                    "" if got is None else got.value,
                    "empty" if got is None else got.cell.status,
                    None if got is None else got.cell.coverage,
                    source,
                    None if source is None else ExtraKey(sha, name, source),
                )
            )
        for cell in cells:
            _judge(cell, latest, drafts)
        recheck = (src.page, src.row) in accepted or any(
            c.extra and c.source_page is not None and (c.source_page, c.name) in extra_changes
            for c in cells
        )
        ocr, merged = src.page in ocr_pages, src.page in merged_pages
        rows.append(
            _Row(
                src.page,
                src.row,
                cells,
                max((c.status for c in cells), key=lambda s: SEVERITY.get(s, 0)),
                recheck,
                ocr,
                merged,
                _review(cells, ocr=ocr, merged=merged),
                src,
            )
        )
    order = [*table.columns, *(names.fields[n] for n in table.extra_names)]
    return _Ctx(
        run,
        table,
        names,
        rows,
        {key: i for i, key in enumerate(order)},
        _numeric_columns(rows, order),
        {(r.page, r.row): r for r in rows},
        latest,
        drafts,
        extra_changes,
        ocr_pages,
    )


def _numeric_columns(rows: list[_Row], order: list[str]) -> dict[str, bool]:
    """Return whether each column is numeric: half its non-empty values or more parse as numbers."""
    out = {}
    for i, key in enumerate(order):
        values = [r.cells[i].value for r in rows if r.cells[i].value.strip()]
        out[key] = bool(values) and 2 * sum(_number(v) is not None for v in values) >= len(values)
    return out


# --- filters -----------------------------------------------------------------------------------
@dataclass(frozen=True)
class Filters:
    """The table screen's filters, sort and paging, as the query string gives them."""

    statuses: tuple[str, ...] = ()
    column: str | None = None
    page: int | None = None
    review: str = "any"
    flagged: bool = False
    recheck: bool = False
    ocr: bool = False
    merged: bool = False
    q: str = ""
    sort: str | None = None
    desc: bool = False
    offset: int = 0


def parse_filters(query: Mapping[str, list[str]], ctx: _Ctx) -> Filters:
    """Read the filters from a query string; ``BadRequest`` if one cannot be used."""
    statuses = tuple(s for v in query.get("status", []) for s in v.split(",") if s)
    for status in statuses:
        if status not in STATUS_ORDER:
            msg = f"unknown status {status!r}"
            raise BadRequest(msg)
    review = _one(query, "review") or "any"
    if review not in REVIEWS:
        msg = f"review must be one of {', '.join(REVIEWS)}"
        raise BadRequest(msg)
    column = _one(query, "column") or None
    if column is not None and column not in ctx.index:
        msg = f"unknown column {column!r}"
        raise BadRequest(msg)
    sort = _one(query, "sort") or None
    if sort is not None and sort not in (ctx.names.page, ctx.names.row, *ctx.index):
        msg = f"cannot sort by {sort!r}"
        raise BadRequest(msg)
    return Filters(
        statuses=statuses,
        column=column,
        page=_int(query, "page", 0),
        review=review,
        flagged=_flag(query, "flagged"),
        recheck=_flag(query, "recheck"),
        ocr=_flag(query, "ocr"),
        merged=_flag(query, "merged"),
        q=(_one(query, "q") or "").casefold(),
        sort=sort,
        desc=_flag(query, "desc"),
        offset=_int(query, "offset", 0) or 0,
    )


def _selected(cell: _Cell, f: Filters) -> bool:
    """Whether ``cell`` is one the status and column filters ask for."""
    return (not f.statuses or cell.status in f.statuses) and f.column in (None, cell.key)


def _row_matches(row: _Row, f: Filters) -> bool:  # noqa: PLR0911
    if f.page is not None and row.page != f.page:
        return False
    if (f.statuses or f.column is not None) and not any(_selected(c, f) for c in row.cells):
        return False
    if f.flagged and not any(c.status not in UNFLAGGED for c in row.cells):
        return False
    if (f.recheck and not row.recheck) or (f.ocr and not row.ocr) or (f.merged and not row.merged):
        return False
    if f.q and not any(f.q in c.value.casefold() for c in row.cells):
        return False
    match f.review:
        case "unreviewed":
            return any(
                c.status not in UNFLAGGED and c.state in ("none", "stale") for c in row.cells
            )
        case "correct" | "changed" | "unsure":
            return any(c.state == f.review for c in row.cells)
        case "note":
            return any(c.note for c in row.cells)
    return True


def _ordered(ctx: _Ctx, f: Filters) -> list[_Row]:
    """Return every row in the sort order (table order is page, then row)."""
    sort = f.sort or ctx.names.page
    if sort == ctx.names.page:
        return sorted(ctx.rows, key=lambda r: (r.page, r.row), reverse=f.desc)
    if sort == ctx.names.row:
        return sorted(ctx.rows, key=lambda r: (r.row, r.page), reverse=f.desc)
    position, numeric = ctx.index[sort], ctx.numeric[sort]
    keyed: list[tuple[Any, _Row]] = []
    blank: list[_Row] = []
    for row in ctx.rows:
        value = row.cells[position].value
        key = _number(value) if numeric else (value.casefold() if value else None)
        if key is None:
            blank.append(row)
        else:
            keyed.append((key, row))
    keyed.sort(key=lambda pair: pair[0], reverse=f.desc)
    return [row for _, row in keyed] + blank


# --- the endpoints: runs -----------------------------------------------------------------------
def _progress(
    project: Path, summary: RunSummary, verdicts: Mapping[Key, Verdict], shas: set[str]
) -> dict[str, Any]:
    flagged = sum(summary.flagged.values())
    reviewed = 0
    if summary.sha256 in shas and flagged:
        try:
            run = sources.load(project, summary.id)
        except NotFound:
            run = None
        if run is not None:
            items = population([run], QueueSettings(statuses=FLAGGED, run=summary.id))
            reviewed = sum(1 for i in items if review_state(i, verdicts) not in ("none", "stale"))
    return {"reviewed": reviewed, "flagged": flagged, "done": flagged > 0 and reviewed >= flagged}


def _run_line(
    project: Path, summary: RunSummary, verdicts: Mapping[Key, Verdict], shas: set[str]
) -> dict[str, Any]:
    return {
        "id": summary.id,
        "short_id": summary.id[:8],
        "started": summary.started,
        "ended": summary.ended,
        "model": summary.model,
        "quotable": summary.quotable,
        "tables": len(summary.tables),
        "rows": summary.rows,
        "cells": summary.cells,
        "flagged": summary.flagged,
        "flagged_total": sum(summary.flagged.values()),
        "ocr_pages": summary.ocr_pages,
        "cost": sources.cost_of(project, summary.id),
        "review": _progress(project, summary, verdicts, shas),
    }


def runs_list(request: Request) -> dict[str, Any]:
    """``GET /api/runs?document=&model=``: the runs, grouped by document (C1)."""
    project = request.project_dir
    document = (_one(request.query, "document") or "").casefold()
    model = _one(request.query, "model") or ""
    summaries, unreadable = list_runs(project)
    shown = [
        s
        for s in summaries
        if (not document or document in s.name.casefold()) and (not model or s.model == model)
    ]
    verdicts = sources.stores(project)[0].latest()
    shas = {key.sha256 for key in verdicts}
    groups: dict[str, list[RunSummary]] = {}
    for summary in shown:
        groups.setdefault(summary.sha256, []).append(summary)
    documents = [
        {
            "name": runs[0].name,
            "sha256": sha,
            "sha_short": sources.short_sha(sha),
            "pages": runs[0].pages,
            "size": runs[0].size,
            "runs": [_run_line(project, s, verdicts, shas) for s in runs],
        }
        for sha, runs in groups.items()
    ]
    return {
        "project": str(project),
        "total_runs": len(summaries),
        "total_documents": len({s.sha256 for s in summaries}),
        "runs": len(shown),
        "documents": documents,
        "models": sorted({s.model for s in summaries}),
        "unreadable": unreadable,
    }


def _notes(run: Run, position: int, table: RunTable) -> list[dict[str, Any]]:
    notes: list[dict[str, Any]] = [
        {
            "kind": "merged",
            "pages": part["pages"],
            "columns": part["columns"],
            "text": f"Merged part: {_pages_text(part['pages'])}, columns "
            + " · ".join(part["columns"]),
        }
        for part in table.merged
    ]
    accepted = sum(p["outcome"] == "accepted" for p in table.proposals) + len(table.extra_changes)
    if accepted:
        plural = "" if accepted == 1 else "s"
        notes.append(
            {
                "kind": "changes",
                "count": accepted,
                "text": f"{accepted} recheck change{plural} accepted",
            }
        )
    for page in sorted(table.bands):
        others = [n + 1 for n, o in enumerate(run.tables) if n != position and page in o.bands]
        if others:
            names = ", ".join(f"Table {n}" for n in others)
            notes.append(
                {
                    "kind": "shared",
                    "page": page,
                    "tables": others,
                    "text": f"Shares p. {page} with {names}; each has its own band of the page",
                }
            )
    return notes


def run_detail(request: Request) -> dict[str, Any]:
    """``GET /api/runs/<id>``: the run, its document, settings and tables (C2)."""
    project = request.project_dir
    run = sources.load(project, request.params[0])
    s = run.summary
    verdicts = sources.stores(project)[0].latest()
    tables = []
    for position, (entry, stored) in enumerate(zip(s.tables, run.tables, strict=False)):
        tables.append(
            {
                "index": entry.index,
                "number": entry.index + 1,
                "label": entry.label,
                "columns": entry.columns,
                "extra_names": entry.extra_names,
                "pages": entry.pages,
                "rows": entry.rows,
                "flagged": entry.flagged,
                "flagged_total": sum(entry.flagged.values()),
                "merged": entry.merged,
                "ocr_pages": entry.ocr_pages,
                "note": _notes(run, position, stored),
            }
        )
    return {
        "id": s.id,
        "short_id": s.id[:8],
        "started": s.started,
        "ended": s.ended,
        "model": s.model,
        "quotable": s.quotable,
        "format": 1,
        "settings": s.settings,
        "document": {
            "name": s.name,
            "path": s.path,
            "size": s.size,
            "sha256": s.sha256,
            "sha_short": sources.short_sha(s.sha256),
            "pages": s.pages,
        },
        "pdf": sources.pdf_status(s),
        "summary": {
            "tables": len(s.tables),
            "rows": s.rows,
            "cells": s.cells,
            "flagged": s.flagged,
            "flagged_total": sum(s.flagged.values()),
            "ocr_pages": s.ocr_pages,
        },
        "cost": sources.cost_of(project, s.id),
        "review": _progress(project, s, verdicts, {k.sha256 for k in verdicts}),
        "tables": tables,
    }


# --- the endpoints: a table --------------------------------------------------------------------
def _context(request: Request) -> _Ctx:
    run = sources.load(request.project_dir, request.params[0])
    _, table = _table_at(run, request.params[1])
    return _build(request.project_dir, run, table)


def _columns(ctx: _Ctx) -> list[dict[str, Any]]:
    per_column: dict[str, dict[str, int]] = {key: {} for key in ctx.index}
    for row in ctx.rows:
        for cell in row.cells:
            counts = per_column[cell.key]
            counts[cell.status] = counts.get(cell.status, 0) + 1
    names = ctx.names
    out: list[dict[str, Any]] = [
        {"key": names.page, "name": names.page, "kind": "page", "numeric": True, "statuses": {}},
        {"key": names.row, "name": names.row, "kind": "row", "numeric": True, "statuses": {}},
    ]
    labels = [(c, c, "column") for c in ctx.table.columns]
    labels += [(names.fields[n], n, "extra") for n in ctx.table.extra_names]
    out += [
        {
            "key": key,
            "name": name,
            "kind": kind,
            "numeric": ctx.numeric[key],
            "statuses": per_column[key],
        }
        for key, name, kind in labels
    ]
    return out


def _summary(ctx: _Ctx) -> dict[str, Any]:
    statuses = dict.fromkeys(STATUS_ORDER, 0)
    for row in ctx.rows:
        for cell in row.cells:
            if not cell.extra:
                statuses[cell.status] = statuses.get(cell.status, 0) + 1
    table = ctx.table
    accepted = sum(p["outcome"] == "accepted" for p in table.proposals) + len(table.extra_changes)
    return {
        "cells": sum(statuses.values()),
        "statuses": statuses,
        "position": table.position,
        "recheck": {"accepted": accepted},
    }


def _row_json(row: _Row) -> dict[str, Any]:
    return {
        "page": row.page,
        "row": row.row,
        "status": row.status,
        "recheck": row.recheck,
        "ocr": row.ocr,
        "merged": row.merged,
        "review": row.review,
        "cells": [
            {
                "key": c.key,
                "name": c.name,
                "extra": c.extra,
                "value": c.value,
                "status": c.status,
                "coverage": c.coverage,
                "source_page": c.source_page,
                "state": c.state,
            }
            for c in row.cells
        ],
    }


def table_rows(request: Request) -> dict[str, Any]:
    """``GET /api/runs/<id>/tables/<n>/rows``: one page of the filtered, sorted rows (C3)."""
    ctx = _context(request)
    f = parse_filters(request.query, ctx)
    matched = [r for r in _ordered(ctx, f) if _row_matches(r, f)]
    return {
        "offset": f.offset,
        "limit": PAGE_SIZE,
        "matched": len(matched),
        "total": len(ctx.rows),
        "columns": _columns(ctx),
        "summary": _summary(ctx),
        "sort": {"column": f.sort or ctx.names.page, "desc": f.desc},
        "rows": [_row_json(r) for r in matched[f.offset : f.offset + PAGE_SIZE]],
    }


def _csv_header(ctx: _Ctx) -> list[str]:
    names, table = ctx.names, ctx.table
    head = [names.page, names.row, *table.columns, *(names.fields[n] for n in table.extra_names)]
    for column in table.columns:
        head += [names.grounding[column], names.coverage[column]]
    for name in table.extra_names:
        head += [names.field_grounding[name], names.field_coverage[name], names.field_source[name]]
    return [*head, names.status, names.changes]


def _csv_row(ctx: _Ctx, row: _Row) -> list[Any]:
    table = ctx.table
    count = len(table.columns)
    own, extras = row.cells[:count], row.cells[count:]
    changes = [
        f'{p["column"]}: "{p["original"]}" -> "{p["proposed"]}"'
        for p in table.proposals
        if p["outcome"] == "accepted" and (p["page"], p["row"]) == (row.page, row.row)
    ]
    for cell in extras:
        if cell.source_page is not None and (cell.source_page, cell.name) in ctx.extra_changes:
            old, new = ctx.extra_changes[cell.source_page, cell.name]
            changes.append(f'{cell.name}: "{old}" -> "{new}"')
    values: list[Any] = [row.page, row.row, *(c.value for c in own), *(c.value for c in extras)]
    for cell in own:
        values += [cell.status, cell.coverage]
    for cell in extras:
        values += [cell.status, cell.coverage, cell.source_page]
    return [*values, row.status, "; ".join(changes)]


def _disposition(kind: str, name: str) -> str:
    plain = re.sub(r"[^A-Za-z0-9._-]", "_", name)
    return f"{kind}; filename=\"{plain}\"; filename*=UTF-8''{quote(name, safe='')}"


def table_csv(request: Request) -> Raw:
    """``GET /api/runs/<id>/tables/<n>/rows.csv``: every matching row, the columns of records()."""
    ctx = _context(request)
    f = parse_filters(request.query, ctx)
    out = io.StringIO(newline="")
    writer = csv.writer(out, lineterminator="\r\n")
    writer.writerow(_csv_header(ctx))
    writer.writerows(_csv_row(ctx, r) for r in _ordered(ctx, f) if _row_matches(r, f))
    stem = Path(ctx.run.summary.name).stem
    index = ctx.table.index + 1
    return Raw(
        out.getvalue().encode("utf-8"),
        "text/csv; charset=utf-8",
        {"Content-Disposition": _disposition("attachment", f"{stem}-table{index}.csv")},
    )


# --- the endpoints: a cell ---------------------------------------------------------------------
def verdict_json(found: Verdict) -> dict[str, Any]:
    """Return a stored verdict as the cell screen and the verdict endpoint show it."""
    return {
        "verdict": found.verdict,
        "time": found.time,
        "run": found.run,
        "extracted": found.extracted,
        "status": found.status,
        "value": found.value,
        "category": found.category,
        "note": found.note,
    }


def _review_json(ctx: _Ctx, cell: _Cell) -> dict[str, Any]:
    key = cell.verdict_key
    found = ctx.latest.get(key) if key is not None else None
    draft = ctx.drafts.get(key) if key is not None else None
    return {
        "state": cell.state,
        "verdict": None if found is None else verdict_json(found),
        "draft": None
        if draft is None
        else {
            "note": draft.note,
            "value": draft.value,
            "category": draft.category,
            "saved_at": draft.saved_at,
        },
        "reviewable": key is not None,
        "key": None if key is None else key.to_json(),
    }


def _ref(row: _Row, cell: _Cell) -> dict[str, Any]:
    return {"page": row.page, "row": row.row, "extra": cell.extra, "name": cell.name}


def _navigation(ctx: _Ctx, f: Filters, row: _Row, cell: _Cell, position: int) -> dict[str, Any]:
    """Return the cell's place in the filter (``n`` of ``of``) and its neighbours."""
    ordered = _ordered(ctx, f)
    here = next(i for i, r in enumerate(ordered) if r is row)
    sequence: list[tuple[int, int]] = []
    matching: list[int] = []
    for i, candidate in enumerate(ordered):
        if not _row_matches(candidate, f):
            continue
        matching.append(i)
        sequence += [
            (i, j)
            for j, c in enumerate(candidate.cells)
            if _selected(c, f) and (not f.flagged or c.status not in UNFLAGGED)
        ]
    at = bisect_left(sequence, (here, position))
    inside = at < len(sequence) and sequence[at] == (here, position)
    following = at + 1 if inside else at

    def cell_at(spot: tuple[int, int] | None) -> dict[str, Any] | None:
        if spot is None:
            return None
        target = ordered[spot[0]]
        return _ref(target, target.cells[spot[1]])

    def row_at(i: int | None) -> dict[str, Any] | None:
        return None if i is None else _ref(ordered[i], ordered[i].cells[position])

    before = bisect_left(matching, here)
    after = before + (1 if before < len(matching) and matching[before] == here else 0)
    return {
        "n": at + 1 if inside else None,
        "of": len(sequence),
        "previous": cell_at(sequence[at - 1] if at > 0 else None),
        "next": cell_at(sequence[following] if following < len(sequence) else None),
        "previous_row": row_at(matching[before - 1] if before > 0 else None),
        "next_row": row_at(matching[after] if after < len(matching) else None),
    }


def _highlights(ctx: _Ctx, row: _Row, cell: _Cell, stored: RunCell | None) -> dict[str, Any]:
    table = ctx.table
    page = row.page
    if cell.extra and cell.source_page is not None:
        page = cell.source_page
    window = crange = area = None
    if not cell.extra:
        areas = table.areas.get(page)
        window = areas.rows.get(row.row) if areas else None
        crange = areas.columns.get(cell.name) if areas else None
        if window is not None and crange is not None:
            area = [crange[0], window[0], crange[1], window[1]]
    matched = None if stored is None else stored.bbox
    stored_page = ctx.run.pages.get(page)
    return {
        "page": page,
        "size": None if stored_page is None else stored_page.size,
        "matched": matched,
        "candidates": [] if stored is None else [b for b in stored.candidates if b != matched],
        "row_window": window,
        "row_label": None if cell.extra else f"row {row.row}",
        "column_range": crange,
        "cell_area": area,
        "band": table.bands.get(page),
        "header": next(
            (layout["header"] for layout in table.layouts if layout["page"] == page), None
        ),
    }


def _merge_json(table: RunTable, row: _Row, cell: _Cell) -> dict[str, Any] | None:
    part = next((p for p in table.merged if row.page in p["pages"]), None)
    if part is None:
        return None
    original = None
    if not cell.extra:
        at = table.columns.index(cell.name)
        original = part["columns"][at] if at < len(part["columns"]) else None
    return {
        "pages": part["pages"],
        "columns": part["columns"],
        "evidence": part["evidence"],
        "original_column": original,
    }


def _cell_json(  # noqa: PLR0913, PLR0917
    ctx: _Ctx, f: Filters, row: _Row, cell: _Cell, position: int, stored: RunCell | None
) -> dict[str, Any]:
    table = ctx.table
    change = ctx.extra_changes.get((cell.source_page, cell.name)) if cell.extra else None
    proposal = None
    if not cell.extra:
        proposal = next(
            (
                p
                for p in table.proposals
                if (p["page"], p["row"], p["column"]) == (row.page, row.row, cell.name)
            ),
            None,
        )
    shown_page = cell.source_page if cell.extra and cell.source_page is not None else row.page
    return {
        "run": ctx.run.summary.id,
        "table": table.index,
        "kind": "extra" if cell.extra else "cell",
        "page": row.page,
        "row": row.row,
        "name": cell.name,
        "key": cell.key,
        "status": cell.status,
        "explanation": EXPLANATIONS.get(cell.status, ""),
        "value": cell.value,
        "matched_text": None if stored is None else stored.matched_text,
        "coverage": cell.coverage,
        "density": None if stored is None else stored.density,
        "places": 0 if stored is None else stored.n_candidates,
        "row_cells": [
            {
                "key": c.key,
                "name": c.name,
                "extra": c.extra,
                "value": c.value,
                "status": c.status,
                "state": c.state,
                "selected": c is cell,
            }
            for c in row.cells
        ],
        "proposal": proposal,
        "ocr": shown_page in ctx.ocr_pages,
        "merge": _merge_json(table, row, cell),
        "extra": None
        if not cell.extra
        else {
            "name": cell.name,
            "source_page": cell.source_page,
            "carried": cell.source_page is not None and cell.source_page != row.page,
            "change": None if change is None else {"original": change[0], "new": change[1]},
        },
        "review": _review_json(ctx, cell),
        "highlights": _highlights(ctx, row, cell, stored),
        "nav": _navigation(ctx, f, row, cell, position),
    }


def _cell_answer(request: Request, *, extra: bool) -> dict[str, Any]:
    run_id, table_n, page_text, row_text, name = request.params
    ctx = _context(Request(request.project_dir, (run_id, table_n)))
    found = ctx.by_position.get((_digits(page_text, "page"), _digits(row_text, "row")))
    if found is None:
        raise NotFound("no such row")
    cell = next((c for c in found.cells if c.name == name and c.extra == extra), None)
    if cell is None:
        raise NotFound("no such extra field" if extra else "no such column")
    f = parse_filters(request.query, ctx)
    if extra:
        got = ctx.table.extra_fields.get(found.page, {}).get(name)
        stored = None if got is None else got.cell
    else:
        stored = found.src.cells.get(name)
    return _cell_json(ctx, f, found, cell, found.cells.index(cell), stored)


def table_cell(request: Request) -> dict[str, Any]:
    """``GET /api/runs/<id>/tables/<n>/cells/<page>/<row>/<column>``: one cell (C4, C5)."""
    return _cell_answer(request, extra=False)


def extra_cell(request: Request) -> dict[str, Any]:
    """``GET /api/runs/<id>/tables/<n>/cells/<page>/<row>/extra/<name>``: one extra field."""
    return _cell_answer(request, extra=True)


# --- the endpoints: pages and the PDF ----------------------------------------------------------
def page_data(request: Request) -> dict[str, Any]:
    """``GET /api/runs/<id>/pages/<page>``: the page's size, words and the tables on it."""
    run = sources.load(request.project_dir, request.params[0])
    page = _digits(request.params[1], "page")
    stored = run.pages.get(page)
    if stored is None:
        raise NotFound("no table of this run is on that page, so no text was kept for it")
    return {
        "page": page,
        "size": stored.size,
        "words": stored.words,
        "ocr": any(page in t.ocr_pages for t in run.tables),
        "tables": [
            {
                "index": t.index,
                "number": t.index + 1,
                "band": t.bands.get(page),
                "header": next((x["header"] for x in t.layouts if x["page"] == page), None),
            }
            for t in run.tables
            if page in t.pages
        ],
    }


def page_image(request: Request) -> Raw:
    """``GET /api/runs/<id>/pages/<page>.png``: the page rendered from the PDF."""
    run = sources.load(request.project_dir, request.params[0])
    page = _digits(request.params[1], "page")
    return Raw(sources.page_png(run.summary, page), "image/png")


def pdf_file(request: Request) -> Raw:
    """``GET /api/runs/<id>/pdf``: the PDF itself, only when its SHA-256 still matches."""
    run = sources.load(request.project_dir, request.params[0])
    name = run.summary.name
    data = sources.pdf_bytes(run.summary)
    return Raw(data, "application/pdf", {"Content-Disposition": _disposition("inline", name)})


_RUN = r"/api/runs/([^/]+)"
_TABLE = _RUN + r"/tables/([^/]+)"
ROUTES: list[Route] = [
    Route("GET", r"/api/runs", runs_list),
    Route("GET", _RUN, run_detail),
    Route("GET", _TABLE + r"/rows", table_rows),
    Route("GET", _TABLE + r"/rows\.csv", table_csv),
    Route("GET", _TABLE + r"/cells/([0-9]+)/([0-9]+)/extra/([^/]+)", extra_cell),
    Route("GET", _TABLE + r"/cells/([0-9]+)/([0-9]+)/([^/]+)", table_cell),
    Route("GET", _RUN + r"/pages/([^/.]+)", page_data),
    Route("GET", _RUN + r"/pages/([^/.]+)\.png", page_image),
    Route("GET", _RUN + r"/pdf", pdf_file),
]
