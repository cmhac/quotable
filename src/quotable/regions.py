"""
A table's part of a page that holds more than one table.

The discovery answer gives the words of each table's first and last data row on the page.
Looking those up in the text layer gives the vertical band the table occupies; the table is
then grounded, position-checked and rechecked against only that band, so words two tables
share (``DESCRIPTION``, amounts) cannot cross-match.

Deliberately left out: tables side by side (they share vertical space, so their bands
overlap and the page is rejected) and any fallback to the whole page when a band cannot be
isolated.
"""

from quotable.grounding import find_candidates
from quotable.schema import ExtractionError
from quotable.text import Layer, tokenize

BAND_MARGIN = 4.0  # pt added above the first row and below the last row
WHOLE_WIDTH = 1e9


def locate(layer: Layer, text: str, which: str) -> tuple[float, float] | None:
    """
    Return the (top, bottom) of the line of ``layer`` that holds the words ``text``.

    With several matches, ``which == "first"`` takes the topmost and anything else the
    bottommost. ``None`` if the words are not in the layer.
    """
    tokens = tokenize(text)
    if not tokens:
        return None
    boxes = [layer.bbox(c.start, c.end) for c in find_candidates(layer, tokens)]
    if not boxes:
        return None
    pick = min(boxes, key=lambda b: b[1]) if which == "first" else max(boxes, key=lambda b: b[3])
    return pick[1], pick[3]


def table_layers(page: int, layer: Layer, tables: list[tuple[str, str, str]]) -> list[Layer]:
    """
    Return each table's layer for ``page``.

    ``tables`` holds (label, first row, last row) for every table on the page. A page with
    one table keeps the whole layer. With several, each table gets the band from its first
    row to its last row; ``ExtractionError`` if a row is not found or two bands overlap.
    """
    if len(tables) < 2:  # noqa: PLR2004
        return [layer for _ in tables]
    bands: list[tuple[float, float]] = []
    for label, first, last in tables:
        top = locate(layer, first, "first")
        bottom = locate(layer, last, "last")
        for which, found in (("first", top), ("last", bottom)):
            if found is None:
                msg = (
                    f"page {page}: table {label!r}: its {which} row was not found in the text layer"
                )
                raise ExtractionError(msg)
        assert top is not None
        assert bottom is not None
        if bottom[1] < top[0]:
            msg = f"page {page}: table {label!r}: its last row is above its first row"
            raise ExtractionError(msg)
        bands.append((top[0] - BAND_MARGIN, bottom[1] + BAND_MARGIN))
    for i, (a_top, a_bottom) in enumerate(bands):
        for j in range(i + 1, len(bands)):
            b_top, b_bottom = bands[j]
            if a_top < b_bottom and b_top < a_bottom:
                msg = (
                    f"page {page}: tables {tables[i][0]!r} and {tables[j][0]!r} overlap "
                    "vertically (side-by-side tables are not supported)"
                )
                raise ExtractionError(msg)
    return [layer.crop(top, bottom, -WHOLE_WIDTH, WHOLE_WIDTH) for top, bottom in bands]
