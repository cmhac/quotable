"""Build small `Table` objects from real text layers, for the offline merge tests (no model)."""

from pathlib import Path

import pymupdf

from quotable.steps.layout import page_layouts
from quotable.table import PageResult, Problem, Table, ground_document
from quotable.text.layer import load_layer

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


def failed_table(
    label: str = "t",
    problems: list[Problem] | None = None,
    *,
    tmp_path: Path | None = None,
    columns: list[str] | None = None,
    pages: list[list[dict[str, str]]] | None = None,
) -> Table:
    """
    Return a failed `Table` (spec 019): by default empty, as a table that failed in discovery.

    With ``pages`` (and ``tmp_path``) it also holds those extracted pages, as a table that
    failed on one page of several does. ``problems`` defaults to one ``discovery`` problem.
    """
    problems = problems or [Problem("discovery", (1,), "schema discovery returned: no columns")]
    if pages is None:
        return Table(columns or [], [], {}, {}, {}, label=label, problems=problems)
    assert tmp_path is not None
    names = columns or ["A", "B"]
    xs = [50.0 + 150.0 * i for i in range(len(names))]
    table = build_table(tmp_path, names, pages, xs=xs, label=label)
    table.problems = problems
    return table
