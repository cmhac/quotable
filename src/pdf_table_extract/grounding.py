"""
Ground extracted values against a page's text layer.

Adapted from google/langextract's resolver (Apache-2.0): an exact token match
first, then a fuzzy match by longest common subsequence that must cover enough of
the value (``FUZZY_THRESHOLD``) in a dense enough span (``FUZZY_MIN_DENSITY``).
Grounding only says *whether* a value is printed on the page; where it sits is the
job of :mod:`pdf_table_extract.position`.
"""

import math
import statistics
from dataclasses import dataclass, field
from typing import NamedTuple

from pdf_table_extract.text import Bbox, Layer, tokenize

FUZZY_THRESHOLD = 0.75  # langextract _FUZZY_ALIGNMENT_MIN_THRESHOLD
FUZZY_MIN_DENSITY = 1 / 3  # langextract _FUZZY_ALIGNMENT_MIN_DENSITY

# Statuses that need no review.
UNFLAGGED = ("exact", "empty", "not_on_page")
# Worst-first ordering used to compare cells and summarise a row.
SEVERITY = {
    "exact": 0,
    "fuzzy": 1,
    "incomplete": 2,
    "misplaced": 3,
    "untokenized": 4,
    "ungrounded": 5,
}


class LcsSpan(NamedTuple):
    """Best source span containing ``matches`` tokens of the extraction."""

    matches: int
    start: int
    end: int

    @property
    def span_len(self) -> int:
        """Return the number of source tokens the span covers."""
        return 0 if self.start < 0 else self.end - self.start + 1


@dataclass
class Candidate:
    """One place in the page text where a value was found."""

    start: int
    end: int
    status: str  # exact | fuzzy
    coverage: float
    density: float


@dataclass
class FieldGrounding:
    """How one extracted value was (or was not) found in the text layer."""

    status: str  # exact | fuzzy | misplaced | ungrounded | untokenized | empty | not_on_page
    coverage: float | None = None
    density: float | None = None
    n_candidates: int = 0
    matched_text: str | None = None
    bbox: Bbox | None = None
    candidates: list[Candidate] = field(default_factory=list)  # every place found


def best_lcs_spans(source: list[str], extraction: list[str]) -> dict[int, LcsSpan]:
    """
    Return the tightest source span for every achievable match count.

    O(n*m^2) dynamic programme with rolling rows. Tracking every match count k
    lets the caller fall back to a denser span with k-1 matches when the
    maximum-match span fails the density gate.
    """
    n, m = len(source), len(extraction)
    if n == 0 or m == 0:
        return {}
    prev_row = [[-1] * (m + 1) for _ in range(m + 1)]
    curr_row = [[-1] * (m + 1) for _ in range(m + 1)]
    for j in range(m + 1):
        prev_row[j][0] = 0
    best_per_k: dict[int, LcsSpan] = {}
    for i in range(1, n + 1):
        src_tok = source[i - 1]
        curr_row[0][0] = i
        for k in range(1, m + 1):
            curr_row[0][k] = -1
        for j in range(1, m + 1):
            curr_row[j][0] = i
            matches_here = src_tok == extraction[j - 1]
            for k in range(1, m + 1):
                best = max(prev_row[j][k], curr_row[j - 1][k])
                if matches_here:
                    candidate = i - 1 if k == 1 else prev_row[j - 1][k - 1]
                    best = max(best, candidate)
                curr_row[j][k] = best
        end = i - 1
        for k in range(1, m + 1):
            start = curr_row[m][k]
            if start < 0:
                continue
            existing = best_per_k.get(k)
            new_len = end - start + 1
            if (
                existing is None
                or new_len < existing.span_len
                or (new_len == existing.span_len and start < existing.start)
            ):
                best_per_k[k] = LcsSpan(k, start, end)
        prev_row, curr_row = curr_row, prev_row
    return best_per_k


def accept_lcs_match(span: LcsSpan, ext_len: int) -> bool:
    """Apply langextract's coverage and density gates to a fuzzy span."""
    if span.matches == 0 or ext_len == 0 or span.span_len <= 0:
        return False
    needed = math.ceil(ext_len * FUZZY_THRESHOLD)
    return span.matches >= needed and span.matches / span.span_len >= FUZZY_MIN_DENSITY


def find_exact(source: list[str], ext: list[str]) -> list[tuple[int, int]]:
    """Return every ``(start, end_exclusive)`` where ``ext`` occurs contiguously."""
    m = len(ext)
    return [(i, i + m) for i in range(len(source) - m + 1) if source[i : i + m] == ext]


def find_candidates(layer: Layer, value_tokens: list[str]) -> list[Candidate]:
    """Return exact matches, else the best fuzzy match, else nothing."""
    exact = find_exact(layer.tokens, value_tokens)
    if exact:
        return [Candidate(s, e, "exact", 1.0, 1.0) for s, e in exact]
    spans = best_lcs_spans(layer.tokens, value_tokens)
    for k in sorted(spans, reverse=True):
        span = spans[k]
        if accept_lcs_match(span, len(value_tokens)):
            return [
                Candidate(
                    span.start,
                    span.end + 1,
                    "fuzzy",
                    span.matches / len(value_tokens),
                    span.matches / span.span_len,
                )
            ]
    return []


def _pick(
    layer: Layer, found: list[Candidate], row_anchor: float | None, prev: float | None
) -> Candidate:
    """Choose among repeated occurrences using the row's vertical position."""
    if len(found) == 1:
        return found[0]
    if row_anchor is not None:
        return min(found, key=lambda c: (abs(layer.yc(c.start, c.end) - row_anchor), c.start))
    if prev is not None:  # nothing unique in this row: first one below the last row
        below = [c for c in found if layer.yc(c.start, c.end) > prev]
        return min(below or found, key=lambda c: layer.yc(c.start, c.end))
    return found[0]


def ground_row(
    row: dict[str, str], columns: list[str], layer: Layer, prev_anchor: float | None
) -> tuple[dict[str, FieldGrounding], float | None]:
    """
    Ground every value of one row; return per-column results and the row anchor.

    Values that occur once on the page fix the row's vertical position; values
    that occur many times (``FEMA``, ``CA``) take the occurrence nearest to it.
    """
    tokens = {c: tokenize(row[c]) for c in columns}
    found = {c: find_candidates(layer, t) if t else [] for c, t in tokens.items()}
    unique_y = [layer.yc(f[0].start, f[0].end) for f in found.values() if len(f) == 1]
    row_anchor = statistics.median(unique_y) if unique_y else None
    result: dict[str, FieldGrounding] = {}
    for column in columns:
        if not row[column].strip():
            result[column] = FieldGrounding("empty")
        elif not tokens[column]:
            result[column] = FieldGrounding("untokenized")
        elif not found[column]:
            result[column] = FieldGrounding("ungrounded", coverage=0.0)
        else:
            pick = _pick(layer, found[column], row_anchor, prev_anchor)
            result[column] = FieldGrounding(
                pick.status,
                pick.coverage,
                pick.density,
                len(found[column]),
                layer.text(pick.start, pick.end),
                layer.bbox(pick.start, pick.end),
                found[column],
            )
    return result, row_anchor if row_anchor is not None else prev_anchor


def ground_rows(
    rows: list[dict[str, str]], columns: list[str], layer: Layer
) -> list[dict[str, FieldGrounding]]:
    """Ground every value of every row of one page."""
    out = []
    anchor = None
    for row in rows:
        grounded, anchor = ground_row(row, columns, layer, anchor)
        out.append(grounded)
    return out
