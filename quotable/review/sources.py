"""
What the browsing API reads besides ``run.json`` and ``tables.json`` (spec 013, task 007).

Small caches in front of the disk, all keyed by what makes the answer change: the loaded runs (by
their files' size and modification time), the cost log (by its), a PDF's SHA-256 (by path, size
and modification time, so a file is hashed once) and rendered pages (by the document's SHA-256
and the page number, so two runs of one PDF share them). Nothing here writes to the project
folder. Standard library only, apart from PyMuPDF (through ``quotable.steps.extract``), which is
imported when a page is rendered.
"""

import hashlib
import re
import threading
from collections import OrderedDict
from decimal import Decimal
from pathlib import Path
from typing import Any

from quotable.review.routing import NotFound
from quotable.review.verdicts import DraftStore, VerdictStore
from quotable.runs import RUN_FILE, TABLES_FILE, Run, RunSummary, load_run
from quotable.storage import CostRecord, cost_file, runs_dir

_RUN_ID = re.compile(r"[0-9a-f]{32}")
_RUNS = 4
_HASHES = 256
_PAGES = 24
_lock = threading.Lock()
_runs: OrderedDict[tuple[str, str], tuple[Any, Run]] = OrderedDict()
_costs: dict[str, tuple[Any, dict[str, dict[str, Any]]]] = {}
_hashes: dict[tuple[str, int, int], str] = {}
_pages: OrderedDict[tuple[str, int], bytes] = OrderedDict()
_stores: dict[Path, tuple[VerdictStore, DraftStore]] = {}


def clear_caches() -> None:
    """Forget everything cached (the tests use this)."""
    with _lock:
        _runs.clear()
        _costs.clear()
        _hashes.clear()
        _pages.clear()
        _stores.clear()


def short_sha(sha: str) -> str:
    """Return the first and last 4 characters of a SHA-256."""
    return f"{sha[:4]}…{sha[-4:]}"


# --- runs -------------------------------------------------------------------------------------
def load(project_dir: Path, run_id: str) -> Run:
    """Return the run, from the cache when its files have not changed; ``NotFound`` if unusable."""
    if not _RUN_ID.fullmatch(run_id):
        raise NotFound("no such run")
    folder = runs_dir(project_dir) / run_id
    try:
        stamp = tuple(
            (s.st_mtime_ns, s.st_size)
            for s in ((folder / n).stat() for n in (RUN_FILE, TABLES_FILE))
        )
    except OSError:
        raise NotFound("no such run") from None
    key = (str(project_dir), run_id)
    with _lock:
        hit = _runs.get(key)
        if hit is not None and hit[0] == stamp:
            _runs.move_to_end(key)
            return hit[1]
    try:
        run = load_run(project_dir, run_id)
    except KeyError:
        raise NotFound("no such run") from None
    except ValueError:
        raise NotFound(f"run {run_id[:8]} cannot be read") from None
    with _lock:
        _runs[key] = (stamp, run)
        while len(_runs) > _RUNS:
            _runs.popitem(last=False)
    return run


def stores(project_dir: Path) -> tuple[VerdictStore, DraftStore]:
    """Return the project's verdict and draft stores (one pair, so reads are cached)."""
    with _lock:
        if project_dir not in _stores:
            _stores[project_dir] = (VerdictStore(project_dir), DraftStore(project_dir))
        return _stores[project_dir]


# --- costs ------------------------------------------------------------------------------------
def run_costs(project_dir: Path) -> dict[str, dict[str, Any]]:
    """
    Return what each run cost: ``{"kind": "usd", "usd": x}`` or ``{"kind": "unknown"}``.

    A run with no record in the cost log is not in the result (the caller calls it ``free``).
    ``unknown`` means one of its records has no price.
    """
    path = cost_file(project_dir)
    try:
        stat = path.stat()
    except OSError:
        return {}
    stamp = (stat.st_mtime_ns, stat.st_size)
    with _lock:
        hit = _costs.get(str(path))
        if hit is not None and hit[0] == stamp:
            return hit[1]
    totals: dict[str, Decimal | None] = {}
    try:
        with path.open(encoding="utf-8", errors="replace") as handle:
            for text in handle:
                if not text.strip():
                    continue
                try:
                    record = CostRecord.from_line(text)
                except ValueError:
                    continue
                price = None if record.cost_usd is None else Decimal(repr(record.cost_usd))
                before = totals.get(record.run, Decimal(0))
                totals[record.run] = None if price is None or before is None else before + price
    except OSError:
        return {}
    costs: dict[str, dict[str, Any]] = {
        run: {"kind": "unknown"} if total is None else {"kind": "usd", "usd": float(total)}
        for run, total in totals.items()
    }
    with _lock:
        _costs[str(path)] = (stamp, costs)
    return costs


def cost_of(project_dir: Path, run_id: str) -> dict[str, Any]:
    """Return a run's cost: dollars, ``free`` (no record) or ``unknown`` (a record has no price)."""
    return run_costs(project_dir).get(run_id, {"kind": "free"})


# --- the PDF ----------------------------------------------------------------------------------
def file_sha256(path: Path) -> str:
    """Return the SHA-256 of the file at ``path``."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def pdf_status(summary: RunSummary) -> dict[str, Any]:
    """
    Say whether the run's PDF can be used: ``ok``, ``missing`` or ``changed``.

    ``changed`` has the ``expected`` and ``found`` short SHA-256. The file is hashed once for each
    (path, size, modification time).
    """
    path = Path(summary.path)
    try:
        stat = path.stat()
        if not path.is_file():
            raise FileNotFoundError  # noqa: TRY301
        key = (str(path), stat.st_size, stat.st_mtime_ns)
        with _lock:
            found = _hashes.get(key)
        if found is None:
            found = file_sha256(path)
            with _lock:
                if len(_hashes) >= _HASHES:
                    _hashes.clear()
                _hashes[key] = found
    except OSError:
        return {"status": "missing", "path": summary.path}
    if found == summary.sha256:
        return {"status": "ok", "path": summary.path}
    return {
        "status": "changed",
        "path": summary.path,
        "expected": short_sha(summary.sha256),
        "found": short_sha(found),
    }


def usable_pdf(summary: RunSummary) -> Path:
    """Return the PDF's path when it is there and unchanged; ``NotFound`` with the reason if not."""
    status = pdf_status(summary)
    if status["status"] == "missing":
        raise NotFound(f"the PDF is missing: {summary.path}")
    if status["status"] == "changed":
        raise NotFound("the PDF has changed: its SHA-256 no longer matches the run's")
    return Path(summary.path)


def pdf_bytes(summary: RunSummary) -> bytes:
    """Return the PDF's bytes if it is unchanged; ``NotFound`` with the reason if not."""
    return usable_pdf(summary).read_bytes()


def page_png(summary: RunSummary, page: int) -> bytes:
    """Return page ``page`` (1-based) as a PNG, from the cache when it was rendered before."""
    if not 1 <= page <= summary.pages:
        raise NotFound("no such page")
    path = usable_pdf(summary)
    key = (summary.sha256, page)
    with _lock:
        hit = _pages.get(key)
        if hit is not None:
            _pages.move_to_end(key)
            return hit
    import pymupdf  # noqa: PLC0415

    from quotable.steps.extract import render_png  # noqa: PLC0415

    try:
        with pymupdf.open(path) as document:
            png = render_png(document[page - 1])
    except (OSError, ValueError, RuntimeError):
        raise NotFound("the PDF cannot be read") from None
    with _lock:
        _pages[key] = png
        while len(_pages) > _PAGES:
            _pages.popitem(last=False)
    return png
