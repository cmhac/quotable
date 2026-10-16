"""The extracted table with the grounding verdict of every cell."""

from dataclasses import dataclass, field

from gridkey.grounding import SEVERITY, UNFLAGGED, FieldGrounding, ground_rows
from gridkey.layout import PageLayout
from gridkey.position import PageGrounding, check_positions
from gridkey.text import Layer

GROUNDING_SUFFIX = "__grounding"
COVERAGE_SUFFIX = "__coverage"


@dataclass
class PageResult:
    """The rows the model gave for one page."""

    page: int  # 1-based
    rows: list[dict[str, str]]
    absent: tuple[str, ...] = ()  # columns this page does not print


@dataclass
class Row:
    """One extracted row with the grounding of each of its cells."""

    page: int
    row: int  # 1-based within the page
    values: dict[str, str]
    cells: dict[str, FieldGrounding]

    @property
    def status(self) -> str:
        """Return the worst cell status of the row."""
        return max((c.status for c in self.cells.values()), key=lambda s: SEVERITY.get(s, 0))


@dataclass
class Flag:
    """A cell that is not an exact match and needs review."""

    page: int
    row: int
    column: str
    status: str
    coverage: float | None


@dataclass
class Proposal:
    """A value the model gave for a flagged cell that differs from the original."""

    page: int
    row: int  # 1-based within the page
    column: str
    original: str
    proposed: str
    status_before: str
    status_after: str = ""
    outcome: str = ""  # accepted | not_improved | same_tokens | blank_ignored


def ground_document(
    columns: list[str], pages: list[PageResult], layers: dict[int, Layer]
) -> tuple[dict[int, PageGrounding], dict[str, int]]:
    """
    Ground every page, then run the position check over the whole document.

    Columns a page does not print are marked ``not_on_page``. Returns the grounded
    pages by page number and the position-check counts.
    """
    grounded: dict[int, PageGrounding] = {}
    for result in pages:
        rows = [{c: r.get(c, "") for c in columns} for r in result.rows]
        cells = ground_rows(rows, columns, layers[result.page])
        for row_cells in cells:
            row_cells.update({c: FieldGrounding("not_on_page") for c in result.absent})
        grounded[result.page] = PageGrounding(rows, cells, layers[result.page])
    position = check_positions(columns, [grounded[r.page] for r in pages])
    return grounded, position


@dataclass(frozen=True)
class MergeEvidence:
    """What the merge step measured when it joined two parts (all per column position)."""

    token_sets: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = ()  # (A's, B's), sorted
    equal_positions: int = 0  # positions where both token sets are equal
    max_x_difference: float = 0.0  # points, largest gap between the two grids
    shapes: tuple[str, ...] = ()  # the dominant value shape of each column
    cells: tuple[tuple[int, int], ...] = ()  # qualifying cells (A's, B's) of each column


@dataclass(frozen=True)
class MergedPart:
    """One part of a table that the merge step absorbed into another (spec 007)."""

    pages: tuple[int, ...]  # the pages the absorbed part had
    columns: tuple[str, ...]  # its column names before they were renamed to the table's
    evidence: MergeEvidence


@dataclass
class Table:
    """Everything the pipeline produced for one table of a PDF (``pages`` are its pages only)."""

    columns: list[str]
    pages: list[PageResult]
    layers: dict[int, Layer]
    grounded: dict[int, PageGrounding]
    position: dict[str, int]
    layouts: list[PageLayout] = field(default_factory=list)
    proposals: list[Proposal] = field(default_factory=list)  # what the recheck proposed
    label: str = ""  # the model's short name for the table; the caller's use only
    # pages of this table whose text layer came from OCR (grounding against OCR text can pass
    # OCR errors into the output, so review these more carefully)
    ocr_pages: tuple[int, ...] = ()
    # the parts absorbed by the merge step (spec 007), empty for a table never merged
    merged: tuple[MergedPart, ...] = ()

    def page_rows(self, page: int) -> list[Row]:
        """Return the rows of one page (1-based)."""
        grounding = self.grounded[page]
        return [
            Row(page, i + 1, values, cells)
            for i, (values, cells) in enumerate(zip(grounding.rows, grounding.cells, strict=True))
        ]

    def rows(self) -> list[Row]:
        """Return every row of the document in page order."""
        return [row for result in self.pages for row in self.page_rows(result.page)]

    def records(self) -> list[dict[str, object]]:
        """Return flat rows: page, row, the values, then each column's grounding."""
        out: list[dict[str, object]] = []
        changes: dict[tuple[int, int], list[str]] = {}
        for p in self.proposals:
            if p.outcome == "accepted":
                text = f'{p.column}: "{p.original}" -> "{p.proposed}"'
                changes.setdefault((p.page, p.row), []).append(text)
        for row in self.rows():
            record: dict[str, object] = {"page": row.page, "row": row.row, **row.values}
            for column in self.columns:
                cell = row.cells[column]
                record[column + GROUNDING_SUFFIX] = cell.status
                record[column + COVERAGE_SUFFIX] = cell.coverage
            record["grounding_status"] = row.status
            record["recheck_changes"] = "; ".join(changes.get((row.page, row.row), []))
            out.append(record)
        return out

    def flagged(self) -> list[Flag]:
        """Return every cell whose status needs review."""
        return [
            Flag(row.page, row.row, column, cell.status, cell.coverage)
            for row in self.rows()
            for column, cell in row.cells.items()
            if cell.status not in UNFLAGGED
        ]
