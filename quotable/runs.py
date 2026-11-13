"""
Saved runs: one folder per ``extract_tables`` call in ``.quotable/runs/<run id>/``.

A run keeps what the review app (spec 013) shows without the model, the cache or, except for
page images, the PDF. Two JSON files, so the runs list never loads the big one. Format version
1; ``v`` changes whenever the format does, and a reader skips what it does not know.

``run.json`` (small): ``v``; ``run`` (``id``, ``started`` and ``ended`` as UTC ISO 8601 with
``Z``, ``quotable`` version, ``model``, ``settings``: ``discovery_pages``, ``recheck``, ``audit``,
``sharp_images`` (the last two from spec 014; a run saved before it has neither), ``ocr``
as ``true``, ``false`` or the ``OcrConfig`` fields, ``merge_reworded``, ``max_requests`` and
``extra_fields``, which is ``null`` or each field's ``name``, ``description`` and ``group``
with the ``prompt`` and ``carry_forward``); ``document`` (``name``, absolute ``path``, ``size``,
``sha256``, ``pages``); ``summary`` (``tables``, ``rows``, ``cells``, ``flagged`` by status,
``ocr_pages``); and ``tables``, one entry per table (``index``, ``label``, ``columns``,
``extra_names``, ``pages``, ``rows``, ``flagged``, ``merged`` part count, ``ocr_pages``).
Flagged counts are cells whose status is not in ``UNFLAGGED`` plus each extra field once per
page that prints it, so they are the number of verdicts a full review asks for.

``tables.json``: ``v``; ``pages`` (every page any table is on: ``size`` ``[width, height]`` in
points and ``words`` as ``[text, x0, y0, x1, y1]``, the whole page, OCR text on OCR'd pages);
and ``tables`` in the order ``extract_tables`` returned them, each with ``index``, ``label``,
``columns``, ``pages``, ``ocr_pages``, ``position``, ``layouts`` (``page``, ``columns``,
``source`` and ``header``: ``line``, ``bottom``, column centres ``x``, or ``null``), ``bands``
(page -> ``[y0, y1]``, only pages shared with another table), ``areas`` (page -> ``rows``:
1-based row number -> ``[y0, y1]``, and ``columns``: name -> ``[x0, x1]``; an open edge of the
position check is clamped to the page), ``merged`` (``pages``, ``columns``, ``evidence``),
``proposals``, ``audit`` (spec 014: the omission audit's items, each ``page``, ``kind``,
``values``, ``outcome`` and ``row``; absent in older runs), ``extra_names``, ``extra_fields``
(page -> name -> ``value``, ``source_page``
and the grounding fields of a cell), ``extra_changes`` (``[page, name, old, new]``) and
``rows`` (``page``, ``row``, ``values`` and ``cells``: column -> ``status``, ``coverage``,
``density``, ``n_candidates``, ``matched_text``, ``bbox`` and ``candidates``, the box of every
place found). Points are rounded to 2 decimals, coverage and density to 4.

A run is written into ``runs/.<id>.tmp/`` and renamed to ``runs/<id>/`` when complete, so a
reader never sees half a run.
"""

import json
import math
import re
import shutil
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from quotable.ocr.config import OcrConfig
from quotable.steps.extra_fields import ExtraFields, ExtraResult, flatten
from quotable.steps.grounding import UNFLAGGED, FieldGrounding
from quotable.steps.layout import Header
from quotable.storage import runs_dir, write_atomic
from quotable.table import Table
from quotable.text.layer import Layer

FORMAT_VERSION = 1
RUN_FILE = "run.json"
TABLES_FILE = "tables.json"
_RUN_ID = re.compile(r"[0-9a-f]{32}")

Box = list[float]


# --- writing ----------------------------------------------------------------------------------
@dataclass(frozen=True)
class RunInfo:
    """What a run records besides its tables: the run, its settings and its document."""

    id: str
    started: str  # UTC, ISO 8601 with a trailing Z
    ended: str
    quotable: str  # version
    model: str  # as the cost log writes it
    discovery_pages: int
    recheck: bool
    ocr: OcrConfig | bool
    merge_reworded: bool
    max_requests: int | None
    extra_fields: ExtraFields | None
    name: str  # the PDF's file name
    path: str  # absolute
    size: int
    sha256: str
    pages: int
    audit: bool = True  # spec 014: the omission audit was on
    sharp_images: bool = True  # spec 014: sharp page images were on


def _pt(value: float) -> float:
    return round(value, 2)


def _box(box: Sequence[float]) -> Box:
    return [_pt(v) for v in box]


def _window(window: tuple[float, float], low: float, high: float) -> Box:
    """Return ``window`` rounded, an open end (``inf``) clamped to ``low`` / ``high``."""
    start, end = window
    return [_pt(low if start == -math.inf else start), _pt(high if end == math.inf else end)]


def _share(value: float | None) -> float | None:
    return None if value is None else round(value, 4)


def _cell(cell: FieldGrounding, layer: Layer) -> dict[str, Any]:
    return {
        "status": cell.status,
        "coverage": _share(cell.coverage),
        "density": _share(cell.density),
        "n_candidates": cell.n_candidates,
        "matched_text": cell.matched_text,
        "bbox": None if cell.bbox is None else _box(cell.bbox),
        "candidates": [_box(layer.bbox(c.start, c.end)) for c in cell.candidates],
    }


def _extra(result: ExtraResult, page_layers: Mapping[int, Layer]) -> dict[str, Any]:
    printed = result.source_page
    layer = page_layers[printed] if printed is not None else Layer()
    return {"value": result.value, "source_page": printed, **_cell(result.grounding, layer)}


def _flagged(table: Table) -> dict[str, int]:
    """Count the flagged cells by status, and each extra field once per page that prints it."""
    counts: dict[str, int] = {}
    for row in table._rows():  # noqa: SLF001 (reading a failed table here must not warn)
        for cell in row.cells.values():
            if cell.status not in UNFLAGGED:
                counts[cell.status] = counts.get(cell.status, 0) + 1
    seen: set[tuple[int | None, str]] = set()
    for results in table.extra_fields.values():
        for name, result in results.items():
            status = result.grounding.status
            if status in UNFLAGGED or (result.source_page, name) in seen:
                continue
            seen.add((result.source_page, name))
            counts[status] = counts.get(status, 0) + 1
    return counts


def _areas(table: Table, page: int, size: tuple[float, float]) -> dict[str, Any]:
    grounding = table.grounded[page]
    width, height = size
    return {
        "rows": {
            str(i + 1): _window(w, 0.0, height) for i, w in sorted(grounding.row_windows.items())
        },
        "columns": {c: _window(w, 0.0, width) for c, w in grounding.column_ranges.items()},
    }


def _header(header: Header | None) -> dict[str, Any] | None:
    if header is None:
        return None
    return {
        "line": _pt(header.line),
        "bottom": _pt(header.bottom),
        "x": {c: _pt(x) for c, x in header.x.items()},
    }


def _problems(table: Table) -> list[dict[str, Any]]:
    return [
        {"stage": p.stage, "pages": list(p.pages), "message": p.message} for p in table.problems
    ]


def _table_data(  # noqa: PLR0913, PLR0917
    index: int,
    table: Table,
    page_layers: Mapping[int, Layer],
    page_sizes: Mapping[int, tuple[float, float]],
    headers: Mapping[int, Header | None],
    bands: Mapping[int, tuple[float, float]],
) -> dict[str, Any]:
    pages = [r.page for r in table.pages]
    rows = [
        {
            "page": row.page,
            "row": row.row,
            "values": row.values,
            "cells": {c: _cell(g, table.layers[row.page]) for c, g in row.cells.items()},
        }
        for row in table._rows()  # noqa: SLF001
    ]
    layouts = [
        {
            "page": page,
            "columns": list(layout.columns),
            "source": layout.source,
            "header": _header(headers.get(page)),
        }
        for page, layout in zip(pages, table.layouts, strict=False)
    ]
    merged = [
        {
            "pages": list(part.pages),
            "columns": list(part.columns),
            "evidence": {
                "token_sets": [[list(a), list(b)] for a, b in part.evidence.token_sets],
                "equal_positions": part.evidence.equal_positions,
                "max_x_difference": _pt(part.evidence.max_x_difference),
                "shapes": list(part.evidence.shapes),
                "cells": [list(pair) for pair in part.evidence.cells],
            },
        }
        for part in table.merged
    ]
    return {
        "index": index,
        "label": table.label,
        "columns": table.columns,
        "pages": pages,
        "ocr_pages": list(table.ocr_pages),
        "failed": table.failed,
        "problems": _problems(table),
        "position": table.position,
        "layouts": layouts,
        "bands": {str(p): _box(b) for p, b in bands.items()},
        "areas": {str(p): _areas(table, p, page_sizes[p]) for p in pages},
        "merged": merged,
        "proposals": [asdict(p) for p in table.proposals],
        "audit": [asdict(a) for a in table.audit],
        "extra_names": list(table.extra_names),
        "extra_fields": {
            str(page): {n: _extra(r, page_layers) for n, r in results.items()}
            for page, results in table.extra_fields.items()
        },
        "extra_changes": [
            [page, name, old, new]
            for (page, name), (old, new) in sorted(table.extra_changes.items())
        ],
        "rows": rows,
    }


def _settings(info: RunInfo) -> dict[str, Any]:
    ocr = (
        info.ocr
        if isinstance(info.ocr, bool)
        else json.loads(json.dumps(asdict(info.ocr), default=str))
    )
    extra = info.extra_fields
    return {
        "discovery_pages": info.discovery_pages,
        "recheck": info.recheck,
        "audit": info.audit,
        "sharp_images": info.sharp_images,
        "ocr": ocr,
        "merge_reworded": info.merge_reworded,
        "max_requests": info.max_requests,
        "extra_fields": None
        if extra is None
        else {
            "fields": [
                {"name": f.name, "description": f.description, "group": group}
                for f, group in flatten(extra)
            ],
            "prompt": extra.prompt,
            "carry_forward": extra.carry_forward,
        },
    }


def _dump(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def write_run(  # noqa: PLR0913, PLR0917
    project_dir: Path,
    info: RunInfo,
    tables: Sequence[Table],
    page_layers: Mapping[int, Layer],
    page_sizes: Mapping[int, tuple[float, float]],
    headers: Sequence[Mapping[int, Header | None]],
    bands: Sequence[Mapping[int, tuple[float, float]]],
) -> Path:
    """
    Write one run to ``runs/<info.id>/`` of ``project_dir`` and return that folder.

    ``page_layers`` are the whole pages' text layers (after OCR) and ``page_sizes`` their
    ``(width, height)`` in points; ``headers`` and ``bands`` hold, per table and page, the
    header found on the whole page and the table's ``(top, bottom)`` on a page it shares.
    Both files go into ``runs/.<id>.tmp/`` and the folder is renamed when complete. On
    ``OSError`` the temporary folder is removed and the error is raised again.
    """
    flagged = [_flagged(t) for t in tables]
    on_pages = sorted({r.page for t in tables for r in t.pages})
    totals: dict[str, int] = {}
    for counts in flagged:
        for status, n in counts.items():
            totals[status] = totals.get(status, 0) + n
    entries: list[dict[str, Any]] = [
        {
            "index": i,
            "label": t.label,
            "columns": t.columns,
            "extra_names": list(t.extra_names),
            "pages": [r.page for r in t.pages],
            "rows": sum(len(r.rows) for r in t.pages),
            "flagged": counts,
            "merged": len(t.merged),
            "ocr_pages": list(t.ocr_pages),
            "failed": t.failed,
            "problems": _problems(t),
        }
        for i, (t, counts) in enumerate(zip(tables, flagged, strict=True))
    ]
    summary = {
        "tables": len(tables),
        "rows": sum(e["rows"] for e in entries),
        "cells": sum(len(r.rows) * len(t.columns) for t in tables for r in t.pages),
        "flagged": totals,
        "ocr_pages": sorted({p for t in tables for p in t.ocr_pages}),
        "failed": sum(t.failed for t in tables),
    }
    run = {
        "v": FORMAT_VERSION,
        "run": {
            "id": info.id,
            "started": info.started,
            "ended": info.ended,
            "quotable": info.quotable,
            "model": info.model,
            "settings": _settings(info),
        },
        "document": {
            "name": info.name,
            "path": info.path,
            "size": info.size,
            "sha256": info.sha256,
            "pages": info.pages,
        },
        "summary": summary,
        "tables": entries,
    }
    big = {
        "v": FORMAT_VERSION,
        "pages": {
            str(p): {
                "size": _box(page_sizes[p]),
                "words": [[w.text, *_box(w.bbox)] for w in page_layers[p].words],
            }
            for p in on_pages
        },
        "tables": [
            _table_data(i, t, page_layers, page_sizes, headers[i], bands[i])
            for i, t in enumerate(tables)
        ],
    }
    base = runs_dir(project_dir)
    temporary = base / f".{info.id}.tmp"
    final = base / info.id
    try:
        write_atomic(temporary / RUN_FILE, _dump(run))
        write_atomic(temporary / TABLES_FILE, _dump(big))
        temporary.replace(final)
    except OSError:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return final


# --- reading ----------------------------------------------------------------------------------
@dataclass
class TableSummary:
    """One table's entry in ``run.json``."""

    index: int
    label: str
    columns: list[str]
    extra_names: list[str]
    pages: list[int]
    rows: int
    flagged: dict[str, int]
    merged: int
    ocr_pages: list[int]
    failed: bool = False  # spec 019; older runs have none
    problems: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class RunSummary:
    """Everything of ``run.json``: the run, its settings, its document and the counts."""

    id: str
    started: str
    ended: str
    quotable: str
    model: str
    settings: dict[str, Any]
    name: str
    path: str
    size: int
    sha256: str
    pages: int
    rows: int
    cells: int
    flagged: dict[str, int]
    ocr_pages: list[int]
    tables: list[TableSummary]
    failed: int = 0  # how many tables failed (spec 019); older runs have none


@dataclass
class RunCell:
    """One cell's grounding (or one extra field's), as stored."""

    status: str
    coverage: float | None
    density: float | None
    n_candidates: int
    matched_text: str | None
    bbox: Box | None
    candidates: list[Box]


@dataclass
class RunExtra:
    """An extra field's value on one page, where it was printed, and its grounding."""

    value: str
    source_page: int | None
    cell: RunCell


@dataclass
class RunRow:
    """One extracted row."""

    page: int
    row: int  # 1-based within the page
    values: dict[str, str]
    cells: dict[str, RunCell]


@dataclass
class RunArea:
    """The areas the position check fitted on one page: row number -> window, column -> range."""

    rows: dict[int, Box] = field(default_factory=dict)
    columns: dict[str, Box] = field(default_factory=dict)


@dataclass
class RunPage:
    """One page's size in points and its words ``(text, x0, y0, x1, y1)``."""

    size: Box
    words: list[list[Any]]


@dataclass
class RunTable:
    """One table of a run; ``layouts``, ``merged`` and ``proposals`` are the stored JSON."""

    index: int
    label: str
    columns: list[str]
    pages: list[int]
    ocr_pages: list[int]
    position: dict[str, int]
    layouts: list[dict[str, Any]]
    bands: dict[int, Box]
    areas: dict[int, RunArea]
    merged: list[dict[str, Any]]
    proposals: list[dict[str, Any]]
    extra_names: list[str]
    extra_fields: dict[int, dict[str, RunExtra]]
    extra_changes: list[list[Any]]
    rows: list[RunRow]
    audit: list[dict[str, Any]] = field(default_factory=list)  # spec 014; older runs have none
    failed: bool = False  # spec 019; older runs have none
    problems: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class Run:
    """A run read back: its summary, the pages its tables are on, and its tables."""

    summary: RunSummary
    pages: dict[int, RunPage]
    tables: list[RunTable]


def _read(path: Path) -> dict[str, Any]:
    """Return the JSON object in ``path``; ``ValueError`` if it is not one of version 1."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("v") != FORMAT_VERSION:
        msg = f"{path} is not a version {FORMAT_VERSION} run file"
        raise ValueError(msg)
    return data


def _summary(data: dict[str, Any], folder: str) -> RunSummary:
    run, document, summary = data["run"], data["document"], data["summary"]
    if run["id"] != folder:
        msg = f"run id {run['id']!r} is not its folder name {folder!r}"
        raise ValueError(msg)
    return RunSummary(
        id=run["id"],
        started=run["started"],
        ended=run["ended"],
        quotable=run["quotable"],
        model=run["model"],
        settings=run["settings"],
        name=document["name"],
        path=document["path"],
        size=document["size"],
        sha256=document["sha256"],
        pages=document["pages"],
        rows=summary["rows"],
        cells=summary["cells"],
        flagged=summary["flagged"],
        ocr_pages=summary["ocr_pages"],
        tables=[TableSummary(**entry) for entry in data["tables"]],
        failed=summary.get("failed", 0),
    )


def _run_cell(data: dict[str, Any]) -> RunCell:
    return RunCell(
        data["status"],
        data["coverage"],
        data["density"],
        data["n_candidates"],
        data["matched_text"],
        data["bbox"],
        data["candidates"],
    )


def _run_table(data: dict[str, Any]) -> RunTable:
    extras = {
        int(page): {
            name: RunExtra(e["value"], e["source_page"], _run_cell(e)) for name, e in row.items()
        }
        for page, row in data["extra_fields"].items()
    }
    areas = {
        int(page): RunArea({int(r): w for r, w in a["rows"].items()}, a["columns"])
        for page, a in data["areas"].items()
    }
    rows = [
        RunRow(r["page"], r["row"], r["values"], {c: _run_cell(g) for c, g in r["cells"].items()})
        for r in data["rows"]
    ]
    return RunTable(
        index=data["index"],
        label=data["label"],
        columns=data["columns"],
        pages=data["pages"],
        ocr_pages=data["ocr_pages"],
        position=data["position"],
        layouts=data["layouts"],
        bands={int(p): b for p, b in data["bands"].items()},
        areas=areas,
        merged=data["merged"],
        proposals=data["proposals"],
        audit=data.get("audit", []),  # runs saved before spec 014 have none
        failed=data.get("failed", False),  # runs saved before spec 019 have none
        problems=data.get("problems", []),
        extra_names=data["extra_names"],
        extra_fields=extras,
        extra_changes=data["extra_changes"],
        rows=rows,
    )


def list_runs(project_dir: Path) -> tuple[list[RunSummary], int]:
    """
    Return the saved runs of the project folder, newest first, and how many were unreadable.

    A run is a folder ``runs/<32 hex digits>/`` with a readable version 1 ``run.json``; one
    that is damaged or of another version is skipped and counted, never raised. Folders that
    start with a dot (a write in progress or left over) and other names are ignored.
    """
    base = runs_dir(project_dir)
    found: list[RunSummary] = []
    skipped = 0
    try:
        folders = sorted(base.iterdir())
    except FileNotFoundError:
        return [], 0
    for folder in folders:
        if not (_RUN_ID.fullmatch(folder.name) and folder.is_dir()):
            continue
        try:
            found.append(_summary(_read(folder / RUN_FILE), folder.name))
        except (OSError, ValueError, KeyError, TypeError):
            skipped += 1
    found.sort(key=lambda r: (r.started, r.id), reverse=True)
    return found, skipped


def load_run(project_dir: Path, run_id: str) -> Run:
    """
    Read a whole run.

    ``KeyError`` if ``run_id`` is not 32 lowercase hex digits or names no run folder;
    ``ValueError`` if the folder's files are damaged or of another version. Page numbers
    and row numbers are ints, as in the tables they came from.
    """
    folder = runs_dir(project_dir) / run_id
    if not _RUN_ID.fullmatch(run_id) or not folder.is_dir():
        raise KeyError(run_id)
    try:
        summary = _summary(_read(folder / RUN_FILE), run_id)
        big = _read(folder / TABLES_FILE)
        pages = {int(p): RunPage(page["size"], page["words"]) for p, page in big["pages"].items()}
        tables = [_run_table(t) for t in big["tables"]]
    except (OSError, KeyError, TypeError) as err:
        msg = f"run {run_id} is damaged ({err!r})"
        raise ValueError(msg) from err
    return Run(summary, pages, tables)
