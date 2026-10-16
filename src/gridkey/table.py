"""The extracted table with the grounding verdict of every cell."""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal, NamedTuple

from gridkey.grounding import SEVERITY, UNFLAGGED, FieldGrounding, ground_rows
from gridkey.layout import PageLayout
from gridkey.position import PageGrounding, check_positions
from gridkey.text import Layer

if TYPE_CHECKING:
    import pandas
    import polars

GROUNDING_SUFFIX = "__grounding"
COVERAGE_SUFFIX = "__coverage"

Kind = Literal["int", "str", "float"]


class OutputNames(NamedTuple):
    """The names of the library's own columns in `Table.records()` and the DataFrames."""

    page: str
    row: str
    grounding: dict[str, str]  # PDF column -> name of its grounding status column
    coverage: dict[str, str]  # PDF column -> name of its coverage column
    status: str
    changes: str


def output_names(columns: list[str]) -> OutputNames:
    """
    Name the library's columns so that none takes the name of a PDF column or of another one.

    PDF columns are never renamed. A library column whose name is taken gets ``_`` appended
    until it is free (spec 008). Without a collision every name is the default one.
    """
    taken = set(columns)

    def free(name: str) -> str:
        while name in taken:
            name += "_"
        taken.add(name)
        return name

    page = free("page")
    row = free("row")
    grounding: dict[str, str] = {}
    coverage: dict[str, str] = {}
    for column in columns:
        grounding[column] = free(column + GROUNDING_SUFFIX)
        coverage[column] = free(column + COVERAGE_SUFFIX)
    return OutputNames(
        page, row, grounding, coverage, free("grounding_status"), free("recheck_changes")
    )


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
        """
        Return flat rows: page, row, the values, then each column's grounding.

        A library column whose name a PDF column already has gets a trailing ``_``.
        """
        names = output_names(self.columns)
        out: list[dict[str, object]] = []
        changes: dict[tuple[int, int], list[str]] = {}
        for p in self.proposals:
            if p.outcome == "accepted":
                text = f'{p.column}: "{p.original}" -> "{p.proposed}"'
                changes.setdefault((p.page, p.row), []).append(text)
        for row in self.rows():
            record: dict[str, object] = {names.page: row.page, names.row: row.row, **row.values}
            for column in self.columns:
                cell = row.cells[column]
                record[names.grounding[column]] = cell.status
                record[names.coverage[column]] = cell.coverage
            record[names.status] = row.status
            record[names.changes] = "; ".join(changes.get((row.page, row.row), []))
            out.append(record)
        return out

    def _frame_columns(self) -> list[tuple[str, Kind]]:
        """Return (name, kind) for every column of `records()`, in order."""
        names = output_names(self.columns)
        out: list[tuple[str, Kind]] = [(names.page, "int"), (names.row, "int")]
        out += [(column, "str") for column in self.columns]
        for column in self.columns:
            out += [(names.grounding[column], "str"), (names.coverage[column], "float")]
        return [*out, (names.status, "str"), (names.changes, "str")]

    def to_pandas(self) -> "pandas.DataFrame":
        """Return `records()` as a pandas DataFrame (ints, strings and a float coverage)."""
        import pandas as pd  # noqa: PLC0415

        columns = self._frame_columns()
        dtypes = {"int": "int64", "str": "str", "float": "float64"}
        frame = pd.DataFrame(self.records(), columns=[name for name, _ in columns])
        return frame.astype({name: dtypes[kind] for name, kind in columns})

    def to_polars(self) -> "polars.DataFrame":
        """Return `records()` as a polars DataFrame (ints, strings and a float coverage)."""
        import polars as pl  # noqa: PLC0415

        dtypes = {"int": pl.Int64, "str": pl.String, "float": pl.Float64}
        schema = {name: dtypes[kind] for name, kind in self._frame_columns()}
        return pl.DataFrame(self.records(), schema=schema)

    def flagged(self) -> list[Flag]:
        """Return every cell whose status needs review."""
        return [
            Flag(row.page, row.row, column, cell.status, cell.coverage)
            for row in self.rows()
            for column, cell in row.cells.items()
            if cell.status not in UNFLAGGED
        ]
