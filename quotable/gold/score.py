"""
Scoring an extraction against hand-typed gold tables (spec 015).

The VRA scorer (``scripts/analysis/gold_eval.py`` in the VRA community-projects repository)
generalized to several tables per page. Per page: gold tables are paired one to one with the
extracted tables, columns are paired by name and then by their values, rows by best similarity,
and every cell where either side has text is compared at three levels (exact, normal, fuzzy).
Recall, precision and accuracy are reported for cells, rows and pages at the ``BENCHMARK`` level.

Nothing here reads a file or a saved run apart from :func:`extracted_from_run`. Standard library
only: the similarity and the assignment are short pure-Python functions (research 4 and 5), not
rapidfuzz and scipy.
"""

import math
import re
import unicodedata
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from quotable.gold.store import GoldError, GoldPage, GoldTable, Sample, key
from quotable.review.queue import wilson

if TYPE_CHECKING:
    from quotable.runs import Run

ROW_MATCH = 0.5  # least similarity for two rows (or two tables) to be the same
COLUMN_MATCH = 0.5  # least value overlap for two columns with different names to be the same
FUZZY = 0.9  # least normalized similarity for a fuzzy cell match
LEVELS = ("exact", "normal", "fuzzy")
BENCHMARK = "normal"  # the cell level that page, row and cell accuracy all use
FOLD = str.maketrans(
    {
        "\u2018": "'",
        "\u2019": "'",
        "\u02bb": "'",  # modifier letter turned comma, which PDFs print as a curly quote
        "\u201c": '"',
        "\u201d": '"',
    }
)


# --- text rules -------------------------------------------------------------------------------
def squash(text: str) -> str:
    """Trim and collapse whitespace."""
    return " ".join(text.split())


def normal(text: str) -> str:
    """
    Fold the differences that do not change a cell's meaning.

    Unlike the VRA scorer, a cell of only dots or dashes stays as it is (spec 014 keeps such
    cells as extracted), so a trailing-period strip that would empty the text is skipped.
    """
    text = text.replace("\u00ad", "")  # soft hyphens are invisible line-break hints
    text = unicodedata.normalize("NFKC", squash(text)).translate(FOLD).casefold()
    text = text.replace("''", '"')  # text layers print a double quote as two singles
    text = re.sub(r"[\u2010-\u2015]", "-", text)
    text = re.sub(r"(\w)- (\w)", r"\1\2", text)  # line-break hyphen kept by a copy
    text = re.sub(r"(\d),(?=\d{3}\b)", r"\1", text).replace("$", "")
    text = re.sub(r"[\s.]+$", "", text) or text
    parts = sorted(p.strip() for p in text.split(";"))
    return "; ".join(p for p in parts if p)


def _lcs(a: str, b: str) -> int:
    """Return the length of the longest common subsequence (one row of memory)."""
    if len(a) < len(b):
        a, b = b, a
    previous = [0] * (len(b) + 1)
    for ca in a:
        current = [0]
        for j, cb in enumerate(b, 1):
            current.append(previous[j - 1] + 1 if ca == cb else max(previous[j], current[j - 1]))
        previous = current
    return previous[-1]


def similarity(a: str, b: str) -> float:
    """
    Return the normalized Indel similarity ``2 * LCS / (len a + len b)`` of two strings.

    It is what the VRA scorer got from ``rapidfuzz.fuzz.ratio``. Equal strings (and two empty
    ones) are 1.0 without any work.
    """
    if a == b:
        return 1.0
    if not a or not b:
        return 0.0
    # shortcut: O(len a * len b) per differing pair, fine for cells (at most 2,000 characters);
    # upgrade to a bit-parallel LCS if a table of very long text cells is ever slow.
    return 2 * _lcs(a, b) / (len(a) + len(b))


def score_cell(gold: str, pred: str) -> dict[str, bool]:
    """Return which match levels a gold and an extracted cell pass."""
    ng, np_ = normal(gold), normal(pred)
    return {
        "exact": squash(gold) == squash(pred),
        "normal": ng == np_,
        "fuzzy": similarity(ng, np_) >= FUZZY,
    }


def column_key(name: str) -> str:
    """Fold a column name to letters and digits."""
    return re.sub(r"[^a-z0-9]", "", name.casefold())


# --- assignment -------------------------------------------------------------------------------
def assign(matrix: Sequence[Sequence[float]]) -> list[tuple[int, int]]:  # noqa: PLR0912
    """
    Pair rows with columns of ``matrix`` one to one so that the total is largest.

    The Hungarian method (shortest augmenting paths, O(n^3)). Returns ``(row, column)`` pairs,
    one for each of the fewer of the rows and columns, sorted. Ties go to whichever the method
    reaches first, which is stable for equal input.
    """
    n = len(matrix)
    m = len(matrix[0]) if n else 0
    if not n or not m:
        return []
    transposed = n > m
    if transposed:
        cost = [[-matrix[i][j] for i in range(n)] for j in range(m)]
        n, m = m, n
    else:
        cost = [[-v for v in row] for row in matrix]
    inf = float("inf")
    u, v = [0.0] * (n + 1), [0.0] * (m + 1)
    owner, way = [0] * (m + 1), [0] * (m + 1)
    for i in range(1, n + 1):
        owner[0] = i
        j0 = 0
        best = [inf] * (m + 1)
        used = [False] * (m + 1)
        while True:
            used[j0] = True
            i0, delta, j1 = owner[j0], inf, 0
            for j in range(1, m + 1):
                if used[j]:
                    continue
                reduced = cost[i0 - 1][j - 1] - u[i0] - v[j]
                if reduced < best[j]:
                    best[j], way[j] = reduced, j0
                if best[j] < delta:
                    delta, j1 = best[j], j
            for j in range(m + 1):
                if used[j]:
                    u[owner[j]] += delta
                    v[j] -= delta
                else:
                    best[j] -= delta
            j0 = j1
            if owner[j0] == 0:
                break
        while j0:
            previous = way[j0]
            owner[j0] = owner[previous]
            j0 = previous
    pairs = [(owner[j] - 1, j - 1) for j in range(1, m + 1) if owner[j]]
    return sorted((c, r) if transposed else (r, c) for r, c in pairs)


# --- what is scored ---------------------------------------------------------------------------
@dataclass(frozen=True)
class TableRows:
    """One extracted table's rows on one page: ``rows`` are in the order of ``columns``."""

    index: int  # the run's table index
    label: str
    columns: list[str]
    rows: list[list[str]]


@dataclass(frozen=True)
class ExtractedTable:
    """An extracted table of a saved run: its columns and its rows page by page."""

    index: int
    label: str
    columns: list[str]
    pages: dict[int, list[list[str]]]

    def on(self, page: int) -> TableRows | None:
        """Return the table's rows on ``page``, or ``None`` if it has none there."""
        rows = self.pages.get(page)
        return TableRows(self.index, self.label, self.columns, rows) if rows else None


def extracted_from_run(run: "Run") -> list[ExtractedTable]:
    """Return the run's tables in the form the scorer reads (the only code that knows the run)."""
    tables = []
    for table in run.tables:
        found: dict[int, list[tuple[int, list[str]]]] = {}
        for row in table.rows:
            cells = [row.values.get(c, "") for c in table.columns]
            found.setdefault(row.page, []).append((row.row, cells))
        pages = {p: [c for _, c in sorted(r, key=lambda x: x[0])] for p, r in found.items()}
        tables.append(ExtractedTable(table.index, table.label, list(table.columns), pages))
    return tables


@dataclass
class Counts:
    """What was counted on a page, a table, a document or everything; counts add."""

    cells: int = 0  # cells where the gold or the extraction has text
    hits: dict[str, int] = field(default_factory=lambda: dict.fromkeys(LEVELS, 0))
    missed: int = 0  # gold has text, extraction blank or absent
    extra: int = 0  # extraction has text, gold blank or absent
    cells_correct: int = 0  # gold has text and the cell passes ``BENCHMARK``
    gold_rows: int = 0
    pred_rows: int = 0
    matched_rows: int = 0
    rows: int = 0  # gold rows plus extracted rows paired with none
    rows_correct: int = 0  # paired gold rows whose every cell passes ``BENCHMARK``

    def add(self, other: "Counts") -> None:
        """Add ``other`` into this one."""
        for name in (
            "cells",
            "missed",
            "extra",
            "cells_correct",
            "gold_rows",
            "pred_rows",
            "matched_rows",
            "rows",
            "rows_correct",
        ):
            setattr(self, name, getattr(self, name) + getattr(other, name))
        for level in LEVELS:
            self.hits[level] += other.hits[level]


@dataclass(frozen=True)
class ColumnPair:
    """How a gold column and an extracted column were paired; one side is ``None`` if alone."""

    gold: str | None
    extracted: str | None
    how: str  # "name", "values" or "none"


@dataclass
class TablePair:
    """A gold table (1-based number on the page) paired with an extracted table."""

    gold: int
    extracted: int  # the run's table index
    label: str
    columns: list[ColumnPair]
    counts: Counts


@dataclass
class PageScore:
    """Everything counted on one page."""

    sha256: str
    page: int
    counts: Counts
    gold_tables: int
    pred_tables: int  # extracted tables with rows on the page
    pairs: list[TablePair] = field(default_factory=list)
    unmatched_gold: list[int] = field(default_factory=list)  # gold table numbers
    unmatched_extracted: list[int] = field(default_factory=list)  # run table indexes
    by_table: dict[int | None, Counts] = field(default_factory=dict)  # None: unmatched gold
    details: list[dict[str, object]] = field(default_factory=list)

    @property
    def counted(self) -> bool:
        """Whether the page counts: the gold or the extraction has rows on it."""
        return self.counts.gold_rows > 0 or self.counts.pred_rows > 0

    @property
    def correct(self) -> bool:
        """Whether every row of the page is right (no missed or extra rows)."""
        return self.counts.rows_correct == self.counts.rows


# --- pairing ----------------------------------------------------------------------------------
def pair_columns(
    gold_cols: list[str],
    gold_rows: list[list[str]],
    pred_cols: list[str],
    pred_rows: list[list[str]],
) -> list[ColumnPair]:
    """
    Pair gold columns with extracted columns: by name where unique, then by shared values.

    Rows are not paired yet, so values are compared as bags: the share of normalized non-empty
    values the two columns have in common. Pairs under ``COLUMN_MATCH`` are dropped; a tie goes
    to the nearer position. Returns every gold column in order, then the unpaired extracted ones.

    shortcut: two columns with the same values pair by position, upgrade if the column pairing
    list in a report shows wrong pairs (compare the columns' cells row by row once rows pair).
    """
    gk = [column_key(c) for c in gold_cols]
    pk = [column_key(c) for c in pred_cols]
    paired: dict[int, tuple[int, str]] = {}
    for i, name_key in enumerate(gk):
        if name_key and gk.count(name_key) == 1 and pk.count(name_key) == 1:
            paired[i] = (pk.index(name_key), "name")
    left_g = [i for i in range(len(gold_cols)) if i not in paired]
    taken = {j for j, _ in paired.values()}
    left_p = [j for j in range(len(pred_cols)) if j not in taken]
    if left_g and left_p:
        bag_g = [Counter(normal(r[i]) for r in gold_rows if normal(r[i])) for i in left_g]
        bag_p = [Counter(normal(r[j]) for r in pred_rows if normal(r[j])) for j in left_p]
        overlap = [
            [sum((bg & bp).values()) / max(sum(bg.values()), sum(bp.values()), 1) for bp in bag_p]
            for bg in bag_g
        ]
        # a tie goes to the nearer position, by far less than any real difference
        matrix = [
            [overlap[a][b] - 1e-6 * abs(a - b) for b in range(len(left_p))]
            for a in range(len(left_g))
        ]
        for a, b in assign(matrix):
            if overlap[a][b] >= COLUMN_MATCH:
                paired[left_g[a]] = (left_p[b], "values")
    taken = {j for j, _ in paired.values()}
    pairs = [
        ColumnPair(
            name,
            pred_cols[paired[i][0]] if i in paired else None,
            paired[i][1] if i in paired else "none",
        )
        for i, name in enumerate(gold_cols)
    ]
    pairs += [ColumnPair(None, c, "none") for j, c in enumerate(pred_cols) if j not in taken]
    return pairs


def _column_map(
    gold_cols: list[str], pred_cols: list[str], pairs: list[ColumnPair]
) -> dict[int, int]:
    """Return gold column index -> extracted column index for the paired columns."""
    used: set[int] = set()
    mapping: dict[int, int] = {}
    for i, pair in enumerate(p for p in pairs if p.gold is not None):
        if pair.extracted is None:
            continue
        j = next(k for k, c in enumerate(pred_cols) if c == pair.extracted and k not in used)
        used.add(j)
        mapping[i] = j
    return mapping


def _row_similarity(g: list[str], p: list[str], cols: dict[int, int]) -> float:
    scores = [
        similarity(normal(g[i]), normal(p[j]))
        for i, j in cols.items()
        if g[i].strip() or p[j].strip()
    ]
    return sum(scores) / len(scores) if scores else 0.0


def pair_rows(
    gold: list[list[str]],
    pred: list[list[str]],
    cols: dict[int, int],
    *,
    equal_first: bool = True,
) -> list[tuple[int, int, float]]:
    """
    Pair gold and extracted rows one to one, keeping pairs at or above ``ROW_MATCH``.

    Rows equal after normalization on the paired columns pair first (they are interchangeable
    and have the largest possible similarity, so this cannot lower the total); the rest are
    assigned by best mean cell similarity. Returns ``(gold index, extracted index, similarity)``.
    """
    if not gold or not pred or not cols:
        return []
    pairs: list[tuple[int, int, float]] = []
    left_g, left_p = list(range(len(gold))), list(range(len(pred)))
    if equal_first:
        waiting: dict[tuple[str, ...], list[int]] = {}
        for b in left_p:
            waiting.setdefault(tuple(normal(pred[b][j]) for j in cols.values()), []).append(b)
        for a in left_g:
            sig = tuple(normal(gold[a][i]) for i in cols)
            if any(sig) and waiting.get(sig):
                pairs.append((a, waiting[sig].pop(0), 1.0))
        done_g, done_p = {a for a, _, _ in pairs}, {b for _, b, _ in pairs}
        left_g = [a for a in left_g if a not in done_g]
        left_p = [b for b in left_p if b not in done_p]
    if left_g and left_p:
        matrix = [[_row_similarity(gold[a], pred[b], cols) for b in left_p] for a in left_g]
        pairs += [
            (left_g[a], left_p[b], matrix[a][b])
            for a, b in assign(matrix)
            if matrix[a][b] >= ROW_MATCH
        ]
    return sorted(pairs)


@dataclass
class _Candidate:
    columns: list[ColumnPair]
    col_map: dict[int, int]
    rows: list[tuple[int, int, float]]

    @property
    def mass(self) -> float:
        return sum(s for _, _, s in self.rows)


def _candidate(gold: GoldTable, pred: TableRows) -> _Candidate:
    columns = pair_columns(gold.columns, gold.rows, pred.columns, pred.rows)
    col_map = _column_map(gold.columns, pred.columns, columns)
    return _Candidate(columns, col_map, pair_rows(gold.rows, pred.rows, col_map))


def pair_tables(
    golds: list[GoldTable], preds: list[TableRows]
) -> list[tuple[int, int, _Candidate]]:
    """
    Pair gold tables with extracted tables on a page, one to one.

    The score of a pair is the total similarity of its paired rows, so a table the pipeline
    cut short still pairs with its gold. A pair needs at least one paired row. Returns
    ``(gold index, extracted index, candidate)``.
    """
    if not golds or not preds:
        return []
    cands = [[_candidate(g, p) for p in preds] for g in golds]
    matrix = [[c.mass for c in row] for row in cands]
    return [(a, b, cands[a][b]) for a, b in assign(matrix) if cands[a][b].rows]


# --- scoring ----------------------------------------------------------------------------------
def _count(  # noqa: PLR0913, PLR0917
    label: str,
    gold: GoldTable | None,
    pred: TableRows | None,
    col_map: dict[int, int],
    row_pairs: list[tuple[int, int, float]],
    details: list[dict[str, object]],
) -> Counts:
    """Count one table pair, or a table with no partner (the other side is ``None``)."""
    gcols, grows = (gold.columns, gold.rows) if gold else ([], [])
    pcols, prows = (pred.columns, pred.rows) if pred else ([], [])
    counts = Counts(gold_rows=len(grows), pred_rows=len(prows), matched_rows=len(row_pairs))
    wrong: set[int] = set()  # gold row numbers with a cell failing the benchmark

    def record(column: str, row: int | None, g: str, p: str) -> None:
        if not (normal(g) or normal(p)):  # blank on both sides
            return
        counts.cells += 1
        levels = score_cell(g, p)
        for level, ok in levels.items():
            counts.hits[level] += ok
        if row is not None and not levels[BENCHMARK]:
            wrong.add(row)
        counts.cells_correct += levels[BENCHMARK] and bool(g.strip())
        counts.missed += bool(g.strip()) and not p.strip()
        counts.extra += bool(p.strip()) and not g.strip()
        if not levels["exact"]:
            best = next((lv for lv in LEVELS if levels[lv]), "none")
            details.append(
                {
                    "table": label,
                    "column": column,
                    "gold_row": row,
                    "gold": g,
                    "extracted": p,
                    "best": best,
                }
            )

    paired_gold = {a: b for a, b, _ in row_pairs}
    paired_pred = set(paired_gold.values())
    unpaired_pred_cols = [j for j in range(len(pcols)) if j not in col_map.values()]
    for a, g in enumerate(grows):
        b = paired_gold.get(a)
        for i, name in enumerate(gcols):
            p = prows[b][col_map[i]] if b is not None and i in col_map else ""
            record(name, a + 1, g[i], p)
        for j in unpaired_pred_cols:
            record(pcols[j], a + 1, "", prows[b][j] if b is not None else "")
    for b, p in enumerate(prows):
        if b not in paired_pred:
            for j, name in enumerate(pcols):
                record(name, None, "", p[j])
    counts.rows = len(grows) + len(prows) - len(row_pairs)
    counts.rows_correct = sum(a + 1 not in wrong for a in paired_gold)
    return counts


NO_MATCH = "(no match)"


def score_page(sha256: str, page: int, golds: list[GoldTable], preds: list[TableRows]) -> PageScore:
    """Score one page: the gold tables typed for it against the extracted tables on it."""
    pairs = pair_tables(golds, preds)
    score = PageScore(sha256, page, Counts(), len(golds), sum(1 for p in preds if p.rows))
    paired_g = {a for a, _, _ in pairs}
    paired_p = {b for _, b, _ in pairs}
    for a, b, cand in pairs:
        pred = preds[b]
        counts = _count(pred.label, golds[a], pred, cand.col_map, cand.rows, score.details)
        score.pairs.append(TablePair(a + 1, pred.index, pred.label, cand.columns, counts))
        score.by_table.setdefault(pred.index, Counts()).add(counts)
    for a, gold in enumerate(golds):
        if a not in paired_g:
            score.unmatched_gold.append(a + 1)
            counts = _count(NO_MATCH, gold, None, {}, [], score.details)
            score.by_table.setdefault(None, Counts()).add(counts)
    for b, pred in enumerate(preds):
        if b not in paired_p and pred.rows:
            score.unmatched_extracted.append(pred.index)
            counts = _count(pred.label, None, pred, {}, [], score.details)
            score.by_table.setdefault(pred.index, Counts()).add(counts)
    for counts in score.by_table.values():
        score.counts.add(counts)
    return score


# --- the report -------------------------------------------------------------------------------
@dataclass(frozen=True)
class RunRef:
    """The run a document was scored against."""

    id: str
    started: str
    model: str
    name: str  # the PDF's file name


@dataclass(frozen=True)
class Unit:
    """One line of the headline table: cell, row or page."""

    name: str
    correct: int
    gold: int
    extracted: int
    either: int

    @property
    def recall(self) -> float | None:
        """Correct over the units in the gold."""
        return self.correct / self.gold if self.gold else None

    @property
    def precision(self) -> float | None:
        """Correct over the units in the extraction."""
        return self.correct / self.extracted if self.extracted else None

    @property
    def accuracy(self) -> float | None:
        """Correct over the units in either."""
        return self.correct / self.either if self.either else None


@dataclass(frozen=True)
class Interval:
    """The share of counted pages that are correct, with its interval (a one-document sample)."""

    share: float
    low: float
    high: float
    confidence: int
    n: int  # counted pages
    sampled: int  # pages in the sample
    pages: int  # pages in the document


@dataclass
class DocScore:
    """The counts of one document."""

    sha256: str
    name: str
    counts: Counts
    pages: int = 0  # sampled pages scored
    counted: int = 0
    correct: int = 0


@dataclass
class TableLine:
    """The counts of one extracted table of one document, or of its unmatched gold tables."""

    sha256: str
    name: str
    index: int | None  # None: gold tables no extracted table matched
    label: str
    counts: Counts


@dataclass
class Report:
    """Everything the score screen and the command print."""

    sample: Sample
    runs: dict[str, RunRef]
    not_scored: list[str]  # names of sampled documents with no usable run
    pages: list[PageScore]
    total: Counts
    units: list[Unit]
    documents: list[DocScore]
    tables: list[TableLine]
    interval: Interval | None
    cells: list[dict[str, object]]
    notes: list[str] = field(default_factory=list)  # about runs left out; set by the caller


@dataclass(frozen=True)
class Progress:
    """How much of the sample is typed and done."""

    done: int
    total: int
    left: list[tuple[str, int]]  # (SHA-256, page) not yet done, in sample order

    @property
    def complete(self) -> bool:
        """Whether every sampled page is done."""
        return self.total > 0 and self.done == self.total


def progress(sample: Sample, pages: dict[str, GoldPage]) -> Progress:
    """Return how many pages of ``sample`` are marked done."""
    left = [(s, p) for s, p in sample.pages if not (g := pages.get(key(s, p))) or not g.done]
    return Progress(len(sample.pages) - len(left), len(sample.pages), left)


def _interval(sample: Sample, pages: list[PageScore], confidence: int = 95) -> Interval | None:
    counted = [p for p in pages if p.counted]
    if len(sample.documents) != 1 or not counted:
        return None
    n, c = len(counted), sum(p.correct for p in counted)
    low, high = wilson(c, n, confidence)
    share = c / n
    total_pages, sampled = sample.documents[0].pages, len(sample.pages)
    # the sample is a share of the document's pages, so the interval narrows like a margin
    # of error does (spec 013 uses the same factor); all pages looked at leaves no doubt
    shrink = (
        0.0
        if sampled >= total_pages
        else math.sqrt((total_pages - sampled) / max(total_pages - 1, 1))
    )
    return Interval(
        share,
        share - (share - low) * shrink,
        share + (high - share) * shrink,
        confidence,
        n,
        sampled,
        total_pages,
    )


def evaluate(
    sample: Sample,
    gold: dict[str, GoldPage],
    extracted: dict[str, tuple[RunRef, list[ExtractedTable]]],
) -> Report:
    """
    Score every sampled page against the chosen run of its document.

    ``extracted`` maps a document's SHA-256 to its run and tables; a sampled document without
    an entry is listed as not scored and left out of the totals. Raises :class:`GoldError` when
    a sampled page is not done, since a score of part of the sample is not an estimate.
    """
    status = progress(sample, gold)
    if not status.complete:
        msg = f"{status.done} of {status.total} sampled pages are done"
        raise GoldError(msg)
    names = {d.sha256: d.name for d in sample.documents}
    pages: list[PageScore] = []
    docs: dict[str, DocScore] = {}
    lines: dict[tuple[str, int | None], TableLine] = {}
    cells: list[dict[str, object]] = []
    for sha, number in sample.pages:
        if sha not in extracted:
            continue
        tables = extracted[sha][1]
        labels = {t.index: t.label for t in tables}
        record = gold[key(sha, number)]
        preds = [rows for t in tables if (rows := t.on(number))]
        page = score_page(sha, number, record.tables, preds)
        pages.append(page)
        doc = docs.setdefault(sha, DocScore(sha, names[sha], Counts()))
        doc.counts.add(page.counts)
        doc.pages += 1
        doc.counted += page.counted
        doc.correct += page.counted and page.correct
        for index, counts in page.by_table.items():
            line = lines.setdefault(
                (sha, index),
                TableLine(sha, names[sha], index, labels.get(index, NO_MATCH), Counts()),
            )
            line.counts.add(counts)
        cells.extend(
            {"document": names[sha], "sha256": sha, "page": number, **d} for d in page.details
        )
    total = Counts()
    for page in pages:
        total.add(page.counts)
    units = [
        Unit(
            "cell",
            total.cells_correct,
            total.cells - total.extra,
            total.cells - total.missed,
            total.cells,
        ),
        Unit("row", total.rows_correct, total.gold_rows, total.pred_rows, total.rows),
        Unit(
            "page",
            sum(p.correct and p.counts.gold_rows > 0 for p in pages),
            sum(p.counts.gold_rows > 0 for p in pages),
            sum(p.counts.pred_rows > 0 for p in pages),
            sum(p.counted for p in pages),
        ),
    ]
    return Report(
        sample=sample,
        runs={sha: ref for sha, (ref, _) in extracted.items() if sha in names},
        not_scored=[names[sha] for sha in names if sha not in extracted],
        pages=pages,
        total=total,
        units=units,
        documents=list(docs.values()),
        tables=sorted(
            lines.values(), key=lambda t: (t.name, t.sha256, t.index is None, t.index or 0)
        ),
        interval=_interval(sample, pages)
        if not any(sha not in extracted for sha in names)
        else None,
        cells=cells,
    )
