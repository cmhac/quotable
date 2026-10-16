"""
Join the parts of one table whose header is worded differently on different pages (spec 007).

Discovery groups pages by their column names (case and punctuation ignored), so a table whose
header reads "Requested Local Match" on pages 1-3 and "Requested Match" on pages 7-9 comes out as
two ``Table``s. This module runs after extraction and before the recheck and joins two tables
only when every independent check passes:

- no shared page, the same column count;
- per position, one column name's words contain the other's (no synonyms, nothing fuzzy), and
  no column is compatible with a different position of the other table;
- the same physical grid (the columns sit at the same x positions);
- the same kind of value in every column;
- enough cells in every column to tell, and exactly one possible partner on each side.

Any doubt, including too little data to judge, means no merge. No model request is made.
"""

import math
import re
import statistics
from dataclasses import dataclass

from gridkey.grounding import FieldGrounding
from gridkey.layout import PageLayout
from gridkey.table import MergedPart, MergeEvidence, PageResult, Table, ground_document
from gridkey.text import Bbox, tokenize

GRID_TOLERANCE = 10.0  # points: how far apart the same column may sit on the two sides
MIN_CELLS = 5  # qualifying cells a column needs on each side
SHAPE_SHARE = 0.8  # share of a column's cells that must have the dominant shape

_GOOD = ("exact", "fuzzy")
_MONTH = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?"
_DATE = re.compile(
    rf"^(?:{_MONTH}\s+\d{{1,2}},?\s+\d{{4}}|\d{{1,2}}\s+{_MONTH}\s+\d{{4}}"
    r"|\d{1,2}/\d{1,2}/\d{2,4}|\d{4}-\d{2}-\d{2})$",
    re.IGNORECASE,
)
_CURRENCY = re.compile(r"^\(?-?\$\s?\d[\d,]*(?:\.\d+)?\)?$")
_PERCENT = re.compile(r"^-?\d[\d,]*(?:\.\d+)?\s?%$")
_INTEGER = re.compile(r"^-?\d[\d,]*$")
_DECIMAL = re.compile(r"^-?\d[\d,]*\.\d+$")
_WORD = re.compile(r"^[^\W\d_]+(?:[-'\u2019.][^\W\d_]+)*\.?$")


@dataclass(frozen=True)
class Rules:
    """The settings of the pair check (the module constants by default)."""

    # share of positions whose words must be equal; 0 turns the rule off. Off by default: on the
    # golden fixture it removed no harmful merge and cost many correct ones (spec 007, Results).
    equal_share: float = 0.0
    grid_tolerance: float = GRID_TOLERANCE
    min_cells: int = MIN_CELLS
    shape_share: float = SHAPE_SHARE
    # tell a one-word value from a longer text, or call both text. Together by default: free-text
    # columns (notes, names) mix one- and two-word values and would have no dominant shape.
    word_text_apart: bool = False


DEFAULT_RULES = Rules()


# --- header words ---------------------------------------------------------------------


def name_tokens(name: str) -> frozenset[str]:
    """Return the comparison tokens of a column name (a multi-level name ``x.y`` has both)."""
    return frozenset(t for part in name.split(".") for t in tokenize(part))


def compatible(a: frozenset[str], b: frozenset[str]) -> bool:
    """Return whether both token sets are non-empty and one contains the other."""
    return bool(a) and bool(b) and (a <= b or b <= a)


@dataclass(frozen=True)
class HeaderCheck:
    """What the two header rows have in common, position by position."""

    same_count: bool
    token_sets: tuple[tuple[frozenset[str], frozenset[str]], ...]
    equal: int  # positions where both token sets are equal
    all_compatible: bool  # every position is compatible
    cross_compatible: bool  # some column is compatible with a *different* position


def header_check(a_columns: list[str], b_columns: list[str]) -> HeaderCheck:
    """Compare two header rows (the facts only; no decision about the half-equal rule)."""
    a = [name_tokens(c) for c in a_columns]
    b = [name_tokens(c) for c in b_columns]
    same_count = len(a) == len(b)
    if not same_count:
        return HeaderCheck(False, (), 0, all_compatible=False, cross_compatible=False)
    pairs = tuple(zip(a, b, strict=True))
    return HeaderCheck(
        True,
        pairs,
        sum(x == y and bool(x) for x, y in pairs),
        all_compatible=all(compatible(x, y) for x, y in pairs),
        cross_compatible=any(
            compatible(a[i], b[j]) for i in range(len(a)) for j in range(len(b)) if i != j
        ),
    )


def half_equal_ok(check: HeaderCheck, share: float = 0.5) -> bool:
    """Return whether at least ``share`` of the positions (rounded up) have equal token sets."""
    needed = math.ceil(share * len(check.token_sets) - 1e-9)
    return check.same_count and bool(check.token_sets) and check.equal >= needed


# --- values and geometry --------------------------------------------------------------


def cell_shape(value: str, *, word_text_apart: bool = False) -> str:  # noqa: PLR0911
    """
    Return the shape of a cell value: what kind of thing it is, ignoring which one.

    With ``word_text_apart`` a one-word value is a ``word``; otherwise it is ``text`` too.
    """
    text = value.strip()
    if _CURRENCY.match(text):
        return "currency"
    if _PERCENT.match(text):
        return "percent"
    if _DATE.match(text):
        return "date"
    if _INTEGER.match(text):
        return "integer"
    if _DECIMAL.match(text):
        return "decimal"
    pieces = text.split()
    if len(pieces) == 1 and _WORD.match(pieces[0]):
        return "word" if word_text_apart else "text"
    if len(pieces) >= 2 and any(ch.isalpha() for ch in text):  # noqa: PLR2004
        return "text"
    return "other"


def dominant_shape(values: list[str], share: float, *, word_text_apart: bool = False) -> str | None:
    """Return the shape held by at least ``share`` of the values, else ``None``."""
    if not values:
        return None
    counts: dict[str, int] = {}
    for value in values:
        shape = cell_shape(value, word_text_apart=word_text_apart)
        counts[shape] = counts.get(shape, 0) + 1
    shape, n = max(counts.items(), key=lambda item: item[1])
    return shape if n / len(values) >= share else None


def qualifying_cells(table: Table, column: str) -> list[tuple[str, Bbox]]:
    """Return (value, box) of the column's non-empty cells grounded exact or fuzzy."""
    cells: list[tuple[str, Bbox]] = []
    for result in table.pages:
        page = table.grounded.get(result.page)
        if page is None:
            continue
        for values, grounding in zip(page.rows, page.cells, strict=True):
            value = values.get(column, "")
            field: FieldGrounding | None = grounding.get(column)
            if value.strip() and field is not None and field.status in _GOOD and field.bbox:
                cells.append((value, field.bbox))
    return cells


def grid_positions(table: Table) -> list[float | None]:
    """Return per column the median horizontal centre of its qualifying cells (points)."""
    positions: list[float | None] = []
    for column in table.columns:
        centres = [(box[0] + box[2]) / 2 for _, box in qualifying_cells(table, column)]
        positions.append(statistics.median(centres) if centres else None)
    return positions


def grid_ok(a: list[float | None], b: list[float | None], tolerance: float) -> bool:
    """Return whether every column sits within ``tolerance`` on both sides, in the same order."""
    if len(a) != len(b) or any(p is None for p in (*a, *b)):
        return False
    xs, ys = [p for p in a if p is not None], [p for p in b if p is not None]
    if any(abs(x - y) > tolerance for x, y in zip(xs, ys, strict=True)):
        return False
    return sorted(range(len(xs)), key=xs.__getitem__) == sorted(range(len(ys)), key=ys.__getitem__)


@dataclass(frozen=True)
class ColumnFacts:
    """What the grounded cells say about one column of one table."""

    position: float | None
    cells: int
    shape: str | None  # the dominant shape; ``None`` when no shape holds the share


def column_facts(table: Table, rules: Rules) -> list[ColumnFacts]:
    """Return per column the position, the number of qualifying cells and the dominant shape."""
    facts: list[ColumnFacts] = []
    for column in table.columns:
        cells = qualifying_cells(table, column)
        centres = [(box[0] + box[2]) / 2 for _, box in cells]
        facts.append(
            ColumnFacts(
                statistics.median(centres) if centres else None,
                len(cells),
                dominant_shape(
                    [v for v, _ in cells], rules.shape_share, word_text_apart=rules.word_text_apart
                ),
            )
        )
    return facts


# --- the pair -------------------------------------------------------------------------


@dataclass(frozen=True)
class Verdict:
    """Whether two tables pass, the name of the first failing check, and what was measured."""

    ok: bool
    failed: str  # "" | shared_page | count | header | half_equal | ambiguity | min_cells |
    # grid | no_shape | shape
    evidence: MergeEvidence


def _sorted(tokens: frozenset[str]) -> tuple[str, ...]:
    return tuple(sorted(tokens))


def pair_verdict(a: Table, b: Table, *, rules: Rules = DEFAULT_RULES) -> Verdict:  # noqa: PLR0911
    """
    Apply requirements 3 to 9 of spec 007 to two tables, ``a`` being the earlier one.

    A condition that cannot be evaluated (no pages, too few cells, no dominant shape) fails.
    """
    head = header_check(a.columns, b.columns)
    base = MergeEvidence(
        token_sets=tuple((_sorted(x), _sorted(y)) for x, y in head.token_sets),
        equal_positions=head.equal,
    )

    def fail(name: str, evidence: MergeEvidence = base) -> Verdict:
        return Verdict(ok=False, failed=name, evidence=evidence)

    if {r.page for r in a.pages} & {r.page for r in b.pages}:
        return fail("shared_page")
    if not head.same_count or not head.token_sets:
        return fail("count")
    if not head.all_compatible:
        return fail("header")
    if not half_equal_ok(head, rules.equal_share):
        return fail("half_equal")
    if head.cross_compatible:
        return fail("ambiguity")
    facts_a, facts_b = column_facts(a, rules), column_facts(b, rules)
    cells = tuple((x.cells, y.cells) for x, y in zip(facts_a, facts_b, strict=True))
    evidence = MergeEvidence(base.token_sets, base.equal_positions, 0.0, (), cells)
    if any(min(x, y) < rules.min_cells for x, y in cells):
        return fail("min_cells", evidence)
    pos_a, pos_b = [f.position for f in facts_a], [f.position for f in facts_b]
    gaps = [
        abs(x - y) for x, y in zip(pos_a, pos_b, strict=True) if x is not None and y is not None
    ]
    evidence = MergeEvidence(base.token_sets, base.equal_positions, max(gaps), (), cells)
    if not grid_ok(pos_a, pos_b, rules.grid_tolerance):
        return fail("grid", evidence)
    if any(x.shape is None or y.shape is None for x, y in zip(facts_a, facts_b, strict=True)):
        return fail("no_shape", evidence)
    shapes = tuple(x.shape or "" for x in facts_a)
    evidence = MergeEvidence(base.token_sets, base.equal_positions, max(gaps), shapes, cells)
    if any(x.shape != y.shape for x, y in zip(facts_a, facts_b, strict=True)):
        return fail("shape", evidence)
    return Verdict(ok=True, failed="", evidence=evidence)


# --- all tables -----------------------------------------------------------------------


def _first_page(table: Table) -> int:
    return min((r.page for r in table.pages), default=0)


def candidate_pairs(tables: list[Table], rules: Rules = DEFAULT_RULES) -> list[tuple[int, int]]:
    """
    Return every (earlier, later) index pair of ``tables`` that passes all the checks.

    "Earlier" is the table whose first page is smaller. Decided on the original tables only.
    """
    pairs: list[tuple[int, int]] = []
    for i in range(len(tables)):
        for j in range(i + 1, len(tables)):
            first, second = sorted((i, j), key=lambda k: _first_page(tables[k]))
            if pair_verdict(tables[first], tables[second], rules=rules).ok:
                pairs.append((first, second))
    return pairs


def mergeable_pairs(tables: list[Table], rules: Rules = DEFAULT_RULES) -> list[tuple[int, int]]:
    """
    Return the pairs that merge: candidate pairs in which each table has no other partner.

    A table with two candidate partners merges with neither (requirement 10).
    """
    pairs = candidate_pairs(tables, rules)
    uses = [0] * len(tables)
    for first, second in pairs:
        uses[first] += 1
        uses[second] += 1
    return [(f, s) for f, s in pairs if uses[f] == 1 and uses[s] == 1]


# --- the merge ------------------------------------------------------------------------


def _rename(rows: list[dict[str, str]], names: dict[str, str]) -> list[dict[str, str]]:
    return [{names.get(k, k): v for k, v in row.items()} for row in rows]


def merge_pair(a: Table, b: Table, evidence: MergeEvidence) -> Table:
    """
    Return one table made of ``a`` and ``b``: ``a``'s names, both parts' pages in order.

    ``b``'s row keys (and its layouts) are renamed to ``a``'s column names by position;
    grounding and the position check are run again over the whole table. Neither input is
    changed. The recheck has not run yet, so there are no proposals to carry over.
    """
    names = dict(zip(b.columns, a.columns, strict=True))
    parts: list[tuple[PageResult, PageLayout | None]] = []
    for table, renamed in ((a, False), (b, True)):
        layouts: list[PageLayout | None] = list(table.layouts) or [None] * len(table.pages)
        for result, layout in zip(table.pages, layouts, strict=True):
            if renamed:
                result = PageResult(  # noqa: PLW2901
                    result.page,
                    _rename(result.rows, names),
                    tuple(names.get(c, c) for c in result.absent),
                )
                if layout is not None:
                    layout = PageLayout(  # noqa: PLW2901
                        tuple(names.get(c, c) for c in layout.columns), layout.source
                    )
            parts.append((result, layout))
    parts.sort(key=lambda part: part[0].page)
    pages = [result for result, _ in parts]
    layouts_out = [layout for _, layout in parts if layout is not None]
    layers = {**a.layers, **b.layers}
    columns = list(a.columns)
    grounded, position = ground_document(columns, pages, layers)
    absorbed = MergedPart(
        pages=tuple(sorted(r.page for r in b.pages)),
        columns=tuple(b.columns),
        evidence=evidence,
    )
    return Table(
        columns,
        pages,
        layers,
        grounded,
        position,
        layouts_out,
        label=a.label,
        ocr_pages=tuple(sorted({*a.ocr_pages, *b.ocr_pages})),
        merged=(*a.merged, absorbed),
    )


def merge_tables(tables: list[Table], *, rules: Rules = DEFAULT_RULES) -> list[Table]:
    """
    Join the tables that are parts of one table, and return the result.

    Candidate pairs are decided on the tables as given; a pair merges only when neither table
    has another candidate partner. Each merged table stands where its earlier part stood.
    When nothing merges the input list itself is returned.
    """
    pairs = mergeable_pairs(tables, rules)
    if not pairs:
        return tables
    # a table is in at most one pair, so no chain of merges has to be followed
    into = dict(pairs)
    absorbed = set(into.values())
    out: list[Table] = []
    for index, table in enumerate(tables):
        if index in absorbed:
            continue
        if index in into:
            partner = tables[into[index]]
            evidence = pair_verdict(table, partner, rules=rules).evidence
            out.append(merge_pair(table, partner, evidence))
        else:
            out.append(table)
    return out
