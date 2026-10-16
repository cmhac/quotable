"""Build small `Table` objects from real text layers, for the offline merge tests (no model)."""

from pathlib import Path

import pymupdf

from quotable.layout import page_layouts
from quotable.table import PageResult, Table, ground_document
from quotable.text import load_layer

ROW_STEP = 14.0
FIRST_ROW_Y = 120.0


def build_table(  # noqa: PLR0913
    tmp_path: Path,
    columns: list[str],
    pages: list[list[dict[str, str]]],
    *,
    xs: list[float],
    first_page: int = 1,
    name: str = "t",
    label: str = "",
) -> Table:
    """
    Draw ``pages`` (rows per page) with column ``i`` at ``xs[i]`` and return its `Table`.

    The PDF has one page per entry, each with the header printed on top; the table's pages are
    numbered from ``first_page`` (the layers are keyed by those numbers, as in a real run).
    A value of ``""`` is left unprinted. Rows are the exact values a perfect model would give.
    """
    path = tmp_path / f"{name}.pdf"
    document = pymupdf.open()
    for rows in pages:
        page = document.new_page(width=612, height=792)
        for x, column in zip(xs, columns, strict=True):
            page.insert_text((x, 100), column.replace(".", " "), fontsize=8)
        for r, row in enumerate(rows):
            for x, column in zip(xs, columns, strict=True):
                if row[column]:
                    page.insert_text((x, FIRST_ROW_Y + r * ROW_STEP), row[column], fontsize=8)
    document.save(path)
    document.close()
    with pymupdf.open(path) as opened:
        layers = {first_page + i: load_layer(p) for i, p in enumerate(opened)}
    results = [PageResult(first_page + i, rows) for i, rows in enumerate(pages)]
    grounded, position = ground_document(columns, results, layers)
    layouts = page_layouts(columns, [layers[r.page] for r in results])
    return Table(columns, results, layers, grounded, position, layouts, label=label)
