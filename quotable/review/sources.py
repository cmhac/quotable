"""
What the browsing API reads besides ``run.json`` and ``tables.json`` (spec 013, task 007).

Small caches in front of the disk, all keyed by what makes the answer change: the loaded runs (by
their files' size and modification time; up to 64 MiB of run files are kept, the least recently
used dropped first), the cost log (by its), a PDF's SHA-256 (by path, size and modification time,
so a file is hashed once) and rendered pages (by the document's SHA-256 and the page number, so
two runs of one PDF share them). Nothing here writes to the project folder. Standard library
only, apart from PyMuPDF (through ``quotable.steps.extract``), which is imported when a page is
rendered. The server answers each request on its own thread and PyMuPDF does not support
threads, so renders run one at a time.
"""

import hashlib
import re
import threading
from collections import OrderedDict
from decimal import Decimal
from pathlib import Path
from typing import Any

from quotable.review.routing import BadRequest, NotFound
from quotable.review.verdicts import DraftStore, VerdictStore
from quotable.runs import RUN_FILE, TABLES_FILE, Run, RunSummary, list_runs, load_run
from quotable.storage import CostRecord, cost_file, runs_dir

_RUN_ID = re.compile(r"[0-9a-f]{32}")
_RUN_BYTES = 64 * 1024 * 1024  # run files kept parsed: about 5 times this in memory
_HASHES = 256
_PAGES = 24
_lock = threading.Lock()
_render_lock = threading.Lock()  # PyMuPDF is not thread-safe: one render at a time
_runs: OrderedDict[tuple[str, str], tuple[Any, Run, int]] = OrderedDict()  # stamp, run, file bytes
_costs: dict[str, tuple[Any, dict[str, dict[str, Any]]]] = {}
_hashes: dict[tuple[str, int, int], str] = {}
_pages: OrderedDict[tuple[str, int], bytes] = OrderedDict()
_stores: dict[Path, tuple[VerdictStore, DraftStore]] = {}
_run_lists: dict[str, tuple[Any, list[RunSummary]]] = {}


def clear_caches() -> None:
    """Forget everything cached (the tests use this)."""
    with _lock:
        _runs.clear()
        _costs.clear()
        _hashes.clear()
        _pages.clear()
        _gold_pages.clear()
        _run_lists.clear()
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
        _runs[key] = (stamp, run, sum(size for _, size in stamp))
        _runs.move_to_end(key)  # a reloaded run is the newest, not left where its old copy was
        # drop the least recently used run while over budget, but never the one just loaded
        while len(_runs) > 1 and sum(entry[2] for entry in _runs.values()) > _RUN_BYTES:
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
        with _render_lock, pymupdf.open(path) as document:
            png = render_png(document[page - 1])
    except (OSError, ValueError, RuntimeError):
        raise NotFound("the PDF cannot be read") from None
    with _lock:
        _pages[key] = png
        while len(_pages) > _PAGES:
            _pages.popitem(last=False)
    return png


# --- the gold check (spec 016) ----------------------------------------------------------------
GOLD_DPI = 200  # sharp enough to zoom in on small print
ROTATIONS = (0, 90, 180, 270)
_GOLD_PAGES = 12
_gold_pages: OrderedDict[tuple[str, int, int], bytes] = OrderedDict()


def saved_runs(project_dir: Path) -> list[RunSummary]:
    """
    Return the saved runs, newest first (``list_runs``), read again only when a run changes.

    shortcut: the stamp is one ``stat`` of every ``run.json``, so a project with thousands of
    runs still pays thousands of ``stat`` calls per request (not file reads); upgrade to a
    watcher if that is ever slow.
    """
    folder = runs_dir(project_dir)
    stamp: list[tuple[str, int, int]] = []
    try:
        for entry in sorted(folder.iterdir()):
            try:
                found = (entry / RUN_FILE).stat()
            except OSError:
                continue  # a run still being written, or a folder that is not a run
            stamp.append((entry.name, found.st_mtime_ns, found.st_size))
    except FileNotFoundError:
        return []
    key = str(project_dir)
    with _lock:
        hit = _run_lists.get(key)
        if hit is not None and hit[0] == stamp:
            return hit[1]
    runs = list_runs(project_dir)[0]
    with _lock:
        _run_lists[key] = (stamp, runs)
    return runs


def usable_run(runs: list[RunSummary]) -> RunSummary | None:
    """
    Return the run to read a document through, from its runs newest first.

    The newest whose PDF is still there unchanged; if none has a usable PDF, the newest (so the
    caller can say why the PDF cannot be used); ``None`` if there are no runs.
    """
    return next((r for r in runs if pdf_status(r)["status"] == "ok"), runs[0] if runs else None)


def newest_run_for(project_dir: Path, sha256: str) -> RunSummary | None:
    """Return the run to read the document with this SHA-256 through (see ``usable_run``)."""
    return usable_run([r for r in saved_runs(project_dir) if r.sha256 == sha256])


def render_gold_page(summary: RunSummary, page: int, rotation: int) -> bytes:
    """Return page ``page`` (1-based) as a PNG at 200 dpi, turned clockwise by ``rotation``."""
    if rotation not in ROTATIONS:
        raise BadRequest("rot must be 0, 90, 180 or 270")
    if not 1 <= page <= summary.pages:
        raise NotFound("no such page")
    path = usable_pdf(summary)
    key = (summary.sha256, page, rotation)
    with _lock:
        hit = _gold_pages.get(key)
        if hit is not None:
            _gold_pages.move_to_end(key)
            return hit
    import pymupdf  # noqa: PLC0415

    scale = GOLD_DPI / 72
    try:
        with _render_lock, pymupdf.open(path) as document:
            matrix = pymupdf.Matrix(scale, scale).prerotate(rotation)
            png = document[page - 1].get_pixmap(matrix=matrix).tobytes("png")
    except (OSError, ValueError, RuntimeError):
        raise NotFound("the PDF cannot be read") from None
    with _lock:
        _gold_pages[key] = png
        while len(_gold_pages) > _GOLD_PAGES:
            _gold_pages.popitem(last=False)
    return png


def line_ends(words: list[list[Any]]) -> list[bool]:
    """
    Say which words end a line, for words in reading order as ``[text, x0, y0, x1, y1]``.

    A word ends a line when it is the last one, or the next word starts further left or is more
    than half a line height higher or lower. The text layer of a PDF has real line numbers; this
    is for the words a run saved (OCR text), which have none.

    shortcut: a geometry guess, wrong for columns of text read across or for rotated lines,
    upgrade if copied OCR text joins or splits lines wrongly.
    """
    ends = []
    for i, word in enumerate(words):
        if i + 1 == len(words):
            ends.append(True)
            continue
        nxt = words[i + 1]
        height = max(word[4] - word[2], 1e-6)
        centre, next_centre = (word[2] + word[4]) / 2, (nxt[2] + nxt[4]) / 2
        ends.append(nxt[1] < word[1] or abs(next_centre - centre) > height / 2)
    return ends


def text_words(project_dir: Path, summary: RunSummary, page: int) -> dict[str, Any]:
    """
    Return a page's words for the selectable text over the page image.

    ``{"width", "height", "words"}`` with each word ``[text, x0, y0, x1, y1, line_end]``, a box
    in points on the page as displayed. The words are the PDF's text layer, except on a page the
    run OCR'd and kept words for, where they are the run's saved (OCR) words.
    """
    if not 1 <= page <= summary.pages:
        raise NotFound("no such page")
    if page in summary.ocr_pages:
        saved = load(project_dir, summary.id).pages.get(page)
        if saved is not None:
            plain = [list(w[:5]) for w in saved.words]
            ends = line_ends(plain)
            words = [[*w, end] for w, end in zip(plain, ends, strict=True)]
            return {"width": saved.size[0], "height": saved.size[1], "words": words}
    path = usable_pdf(summary)
    import pymupdf  # noqa: PLC0415

    try:
        with _render_lock, pymupdf.open(path) as document:
            pg = document[page - 1]
            turn = pg.rotation_matrix
            raw = pg.get_text("words")
            words = [
                [
                    w[4],
                    *(round(v, 2) for v in tuple(pymupdf.Rect(w[:4]) * turn)),
                    i + 1 == len(raw) or raw[i + 1][5:7] != w[5:7],  # block and line numbers
                ]
                for i, w in enumerate(raw)
            ]
            return {"width": pg.rect.width, "height": pg.rect.height, "words": words}
    except (OSError, ValueError, RuntimeError):
        raise NotFound("the PDF cannot be read") from None
