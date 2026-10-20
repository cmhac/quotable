"""
Position check: a value must sit in its own row and column.

Grounding accepts a value printed anywhere on the page, so a value moved to
another row or column still passes. This second pass over the whole document
requires each value to be found where it belongs:

* Row anchors: the y-position of each row, from values that occur exactly once on
  the page (anchors must go down the page in row order). A row owns half the gap to
  its neighbours; rows without evidence are interpolated.
* Column bands: the x-range of each column, pooled over the whole document so a
  page the model got wrong cannot define its own columns.
* Each value is searched for only inside its row window and column region (a blank
  neighbouring cell lends its space). A value repeated from the rows above is
  accepted where the PDF prints it once for a merged cell.

A value found on the page but not in its place is marked ``misplaced``. Rows
without an anchor or columns without a band cannot be judged well; those cells keep
their status and are counted as ``unchecked``.

Deliberately left out (see the original project): the ``incomplete`` verdict for
words of a cell that no value accounts for, per-layout column bands, and sharing
space between unbanded columns.
"""

import math
import statistics
from dataclasses import dataclass

from quotable.steps.grounding import Candidate, FieldGrounding, find_candidates
from quotable.text.layer import Bbox, Layer, tokenize

Window = tuple[float, float]

FIRST_LINE_HALF = 4.0  # pt: a multi-line cell also counts by its first line
DEFAULT_ROW_GAP = 16.0  # pt: row spacing when a page gives no evidence
MIN_ROW_GAP = 4.0  # pt: row anchors must go down the page at least this far apart
MIN_BAND_SUPPORT = 5  # cells needed before a column's x-range is trusted
ROW_PAD = 6.0  # pt: search margin above and below a row window


@dataclass
class PageGrounding:
    """One page's rows with their page-wide grounding, and its text layer."""

    rows: list[dict[str, str]]
    cells: list[dict[str, FieldGrounding]]
    layer: Layer


def _centre(box: Bbox) -> float:
    return (box[1] + box[3]) / 2


def _boxes(page: PageGrounding, grounding: FieldGrounding) -> list[Bbox]:
    return [page.layer.bbox(c.start, c.end) for c in grounding.candidates]


# --- rows ---------------------------------------------------------------------
def _fill_anchors(anchors: dict[int, float], n_rows: int) -> dict[int, float]:
    """Interpolate the anchor of rows that have no evidence."""
    known = sorted(anchors)
    gaps = [(anchors[b] - anchors[a]) / (b - a) for a, b in zip(known, known[1:], strict=False)]
    gap = statistics.median(gaps) if gaps else DEFAULT_ROW_GAP
    out = dict(anchors)
    for i in range(n_rows):
        if i in out:
            continue
        below = max((k for k in known if k < i), default=None)
        above = min((k for k in known if k > i), default=None)
        if below is not None and above is not None:
            share = (i - below) / (above - below)
            out[i] = anchors[below] + (anchors[above] - anchors[below]) * share
        elif below is not None:
            out[i] = anchors[below] + gap * (i - below)
        elif above is not None:
            out[i] = anchors[above] - gap * (above - i)
    return out


def _windows(anchors: dict[int, float], n_rows: int) -> dict[int, Window]:
    """Return each row's vertical extent: half the gap to its neighbours' anchors."""
    if not anchors:
        return {}
    full = _fill_anchors(anchors, n_rows)
    rows = sorted(full)
    out = {}
    for k, row in enumerate(rows):
        y = full[row]
        after = full[rows[k + 1]] - y if k + 1 < len(rows) else None
        before = y - full[rows[k - 1]] if k else after
        before = DEFAULT_ROW_GAP if before is None else before
        after = before if after is None else after
        out[row] = (y - 0.5 * before, y + 0.5 * after)
    return out


def _placed(box: Bbox, windows: dict[int, Window], rows: range | list[int]) -> bool:
    """Say whether the box is in one of these rows (centre or first line)."""
    ys = (_centre(box), box[1] + FIRST_LINE_HALF)
    return any(windows[r][0] <= y <= windows[r][1] for r in rows if r in windows for y in ys)


def _enforce_order(anchors: dict[int, float], weight: dict[int, int]) -> dict[int, float]:
    """Keep the best-supported anchors that go down the page in row order."""
    rows = sorted(anchors)
    best: list[int] = []
    prev: list[int] = []
    for k, row in enumerate(rows):
        score, back = weight[row], -1
        for j in range(k):
            ordered = anchors[row] - anchors[rows[j]] >= MIN_ROW_GAP
            if ordered and best[j] + weight[row] > score:
                score, back = best[j] + weight[row], j
        best.append(score)
        prev.append(back)
    keep: set[int] = set()
    k = max(range(len(rows)), key=best.__getitem__, default=-1)
    while k >= 0:
        keep.add(rows[k])
        k = prev[k]
    return {r: anchors[r] for r in keep}


def _row_windows(
    page: PageGrounding, columns: list[str]
) -> tuple[dict[int, float], dict[int, Window]]:
    """Return the page's row anchors and windows."""
    n_rows = len(page.rows)
    chosen: dict[tuple[int, str], Bbox | None] = {}
    for i, cells in enumerate(page.cells):
        for c in columns:
            boxes = _boxes(page, cells[c])
            only = len(boxes) == 1 and cells[c].candidates[0].status == "exact"
            chosen[i, c] = boxes[0] if only else None
    anchors: dict[int, float] = {}
    for _ in range(2):  # anchors place the rows, which re-select repeated matches
        ys: dict[int, list[float]] = {}
        for (i, _c), box in chosen.items():
            if box is not None:
                ys.setdefault(i, []).append(_centre(box))
        anchors = _enforce_order(
            {r: statistics.median(v) for r, v in ys.items()}, {r: len(v) for r, v in ys.items()}
        )
        windows = _windows(anchors, n_rows)
        for i, cells in enumerate(page.cells):
            for c in columns:
                here = [
                    b
                    for b, k in zip(_boxes(page, cells[c]), cells[c].candidates, strict=True)
                    if k.status == "exact" and _placed(b, windows, [i])
                ]
                chosen[i, c] = here[0] if len(here) == 1 else None
    return anchors, _windows(anchors, n_rows)


# --- columns ------------------------------------------------------------------
def _fit_bands(
    pages: list[PageGrounding], windows: list[dict[int, Window]], columns: list[str]
) -> dict[str, Window]:
    """Return the x-range of every column with enough evidence, pooled over pages."""
    boxes: dict[str, list[Bbox]] = {c: [] for c in columns}
    for page, win in zip(pages, windows, strict=True):
        for i, cells in enumerate(page.cells):
            for c in columns:
                here = [b for b in _boxes(page, cells[c]) if i in win and _placed(b, win, [i])]
                if len(here) == 1:
                    boxes[c].append(here[0])
    return {
        c: (statistics.median(b[0] for b in bs), statistics.median(b[2] for b in bs))
        for c, bs in boxes.items()
        if len(bs) >= MIN_BAND_SUPPORT
    }


def _regions(bands: dict[str, Window]) -> dict[str, Window]:
    """Return the x-range each banded column may occupy (bands may touch or overlap)."""
    order = sorted(bands, key=lambda c: sum(bands[c]) / 2)
    regions = {}
    for k, c in enumerate(order):
        low, high = bands[c]
        left = right = None
        if k:
            prev = bands[order[k - 1]]
            left = prev[1] if prev[1] <= low else (sum(prev) + low + high) / 4
        if k + 1 < len(order):
            nxt = bands[order[k + 1]]
            right = nxt[0] if high <= nxt[0] else (sum(nxt) + low + high) / 4
        regions[c] = (-math.inf if left is None else left, math.inf if right is None else right)
    return regions


def _extent(
    page: PageGrounding, regions: dict[str, Window], order: list[str], row: int, column: str
) -> Window:
    """Return the x-range a cell's text may occupy; blank neighbours lend theirs."""
    x0, x1 = regions[column]
    k = order.index(column)
    for name in order[k + 1 :]:
        if page.rows[row][name].strip():
            break
        x1 = regions[name][1]
    for name in reversed(order[:k]):
        if page.rows[row][name].strip():
            break
        x0 = regions[name][0]
    return x0, x1


# --- judging ------------------------------------------------------------------
def _found_in_place(
    sub: Layer, tokens: list[str], windows: dict[int, Window], rows: range | list[int]
) -> bool:
    candidates: list[Candidate] = find_candidates(sub, tokens)
    return any(_placed(sub.bbox(c.start, c.end), windows, rows) for c in candidates)


def _judge_page(
    page: PageGrounding,
    columns: list[str],
    fit: tuple[dict[int, float], dict[int, Window]],
    bands: dict[str, Window],
    counts: dict[str, int],
) -> None:
    anchors, windows = fit
    regions = _regions(bands)
    order = sorted(bands, key=lambda c: sum(bands[c]) / 2)
    run_start: dict[str, int] = {}  # first row of the run of identical values
    for i, row in enumerate(page.rows):
        for column in columns:
            value = row[column].strip()
            same = i > 0 and value != "" and value == page.rows[i - 1][column].strip()
            start = run_start[column] if same else i
            run_start[column] = start
            tokens = tokenize(value)
            grounding = page.cells[i][column]
            if not tokens or not grounding.candidates:
                continue
            if i not in anchors or column not in bands:
                counts["unchecked"] += 1
            if i not in windows or column not in bands:
                continue
            low, high = windows[i]
            x0, x1 = _extent(page, regions, order, i, column)
            sub = page.layer.crop(low - ROW_PAD, high + ROW_PAD, x0, x1)
            if _found_in_place(sub, tokens, windows, [i]):
                continue
            if start < i and start in windows:  # repeated from the rows above
                top = windows[start][0] - ROW_PAD
                sub = page.layer.crop(top, high + ROW_PAD, x0, x1)
                if _found_in_place(sub, tokens, windows, range(start, i)):
                    continue
            grounding.status = "misplaced"
            counts["misplaced"] += 1


def check_positions(columns: list[str], pages: list[PageGrounding]) -> dict[str, int]:
    """
    Mark grounded cells that are not in their row and column ``misplaced`` (in place).

    ``pages`` are the whole document in page order. Returns the number of cells
    marked ``misplaced`` and the number that could not be judged well (``unchecked``).
    """
    fitted = [_row_windows(p, columns) for p in pages]
    bands = _fit_bands(pages, [w for _, w in fitted], columns)
    counts = {"misplaced": 0, "unchecked": 0}
    for page, fit in zip(pages, fitted, strict=True):
        _judge_page(page, columns, fit, bands, counts)
    return counts
