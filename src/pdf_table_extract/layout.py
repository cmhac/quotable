"""
Page layouts: which columns each page of a document prints.

A document can drop a column part-way through (a column printed on some pages
only). Each page's columns come from its text layer, with the schema's column
names as the vocabulary:

* A page with a printed header takes its columns from it. A header is a line (plus
  the sub-header lines under it) in which most words are column names and that
  names at least ``HEADER_MIN_COLUMNS`` columns; a few header words scattered
  through a data row or a sentence are not a header.
* A page without a header inherits the previous page's layout (leading pages
  without one take the first layout found).
* A column that no header in the document shows is a detection gap, not an absent
  column, so every page keeps it.

Deliberately left out (see the original project): grouping header pages by column
position, choosing a layout for headerless pages by word-position histograms, and
adding columns the schema lacks from header labels.
"""

from dataclasses import dataclass, replace

from pdf_table_extract.text import Bbox, Layer, SrcWord, tokenize

HEADER_MIN_CHARS = 2  # header words of this many characters or fewer are ignored
HEADER_MIN_COLUMNS = 3  # a header names at least this many columns ...
HEADER_MIN_SHARE = 0.5  # ... and at least this share of the schema's columns
HEADER_BLOCK_DEPTH = 16.0  # pt: sub-header lines under the header line
HEADER_LINE_TOL = 3.0  # pt: words this close in y are on the header line
HEADER_LINE_SHARE = 0.6  # share of the header line's words that are column names


@dataclass(frozen=True)
class Header:
    """The column header printed on a page."""

    x: dict[str, float]  # x-centre of every column found
    bottom: float  # y below which the page body starts
    line: float = 0.0  # y of the header's main line


@dataclass(frozen=True)
class PageLayout:
    """Which columns a page prints and how that was decided."""

    columns: tuple[str, ...]
    source: str  # "header" | "inherited"


def _centre(box: Bbox) -> float:
    return (box[1] + box[3]) / 2


def _vocabulary(columns: list[str]) -> set[str]:
    """Return every comparison token of the column names, level by level."""
    return {t for c in columns for part in c.split(".") for t in tokenize(part)}


def find_header(columns: list[str], layer: Layer) -> Header | None:
    """Return the column header printed on the page, or None if it has none."""
    leaves = {
        c: {t for t in tokenize(c.split(".")[-1]) if len(t) > HEADER_MIN_CHARS} for c in columns
    }
    vocabulary = _vocabulary(columns)
    hits = [
        (w, c)
        for w in layer.words
        if (tokens := tokenize(w.text))
        for c in columns
        if tokens[0] in leaves[c]
    ]
    lines: dict[int, set[str]] = {}
    for w, c in hits:
        lines.setdefault(round(_centre(w.bbox) / HEADER_LINE_TOL), set()).add(c)
    # Try the line naming the most columns first, then the others from the top: a
    # sentence above the table can name as many columns as the header does.
    for k in sorted(lines, key=lambda k: (-len(lines[k]), k)):
        if found := _header_at(k * HEADER_LINE_TOL, hits, layer, vocabulary, len(columns)):
            return found
    return None


def _header_at(
    anchor: float,
    hits: list[tuple[SrcWord, str]],
    layer: Layer,
    vocabulary: set[str],
    n_columns: int,
) -> Header | None:
    """Return the header whose main line is at ``anchor``, if the line is one."""
    block = [(w, c) for w, c in hits if abs(_centre(w.bbox) - anchor) <= HEADER_BLOCK_DEPTH]
    nearest: dict[str, SrcWord] = {}
    for w, c in sorted(block, key=lambda h: (abs(_centre(h[0].bbox) - anchor), h[0].bbox[0])):
        nearest.setdefault(c, w)
    on_line = [
        tokens
        for w in layer.words
        if abs(_centre(w.bbox) - anchor) <= HEADER_LINE_TOL and (tokens := tokenize(w.text))
    ]
    share = sum(t[0] in vocabulary for t in on_line) / len(on_line) if on_line else 0
    needed = min(n_columns, max(HEADER_MIN_COLUMNS, HEADER_MIN_SHARE * n_columns))
    if len(nearest) < needed or share < HEADER_LINE_SHARE:
        return None
    return Header(
        {c: (w.bbox[0] + w.bbox[2]) / 2 for c, w in nearest.items()},
        max(_centre(w.bbox) for w in nearest.values()) + 6.0,
        anchor,
    )


def page_layouts(columns: list[str], layers: list[Layer]) -> list[PageLayout]:
    """Return the layout of every page of a document, in page order."""
    headers = [find_header(columns, layer) for layer in layers]
    seen_anywhere = {c for h in headers if h for c in h.x}
    out: list[PageLayout | None] = []
    for header in headers:
        if header is not None:
            printed = tuple(c for c in columns if c in header.x or c not in seen_anywhere)
            out.append(PageLayout(printed, "header"))
        elif out and out[-1] is not None:
            out.append(replace(out[-1], source="inherited"))
        else:
            out.append(None)
    first = next((lay for lay in out if lay is not None), None)
    lead = replace(first, source="inherited") if first else PageLayout(tuple(columns), "inherited")
    return [lay or lead for lay in out]
