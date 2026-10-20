"""The extracted table with the grounding verdict of every cell."""

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal, NamedTuple

from quotable.steps.extra_fields import ExtraResult
from quotable.steps.grounding import SEVERITY, UNFLAGGED, FieldGrounding, ground_rows
from quotable.steps.layout import PageLayout
from quotable.steps.position import PageGrounding, check_positions
from quotable.text.layer import Layer

if TYPE_CHECKING:
    import pandas
    import polars

GROUNDING_SUFFIX = "__grounding"
COVERAGE_SUFFIX = "__coverage"
SOURCE_PAGE_SUFFIX = "__source_page"

Kind = Literal["int", "str", "float", "nullable_int"]


class OutputNames(NamedTuple):
    """The names of the columns in `Table.records()` and the DataFrames (not the PDF's)."""

    page: str
    row: str
    grounding: dict[str, str]  # PDF column -> name of its grounding status column
    coverage: dict[str, str]  # PDF column -> name of its coverage column
    status: str
    changes: str
    fields: dict[str, str]  # extra field -> name of its value column
    field_grounding: dict[str, str]  # extra field -> name of its grounding status column
    field_coverage: dict[str, str]  # extra field -> name of its coverage column
    field_source: dict[str, str]  # extra field -> name of its source page column


def output_names(columns: list[str], fields: Sequence[str] = ()) -> OutputNames:
    """
    Name the library's columns so that none takes the name of a PDF column or of another one.

    PDF columns are never renamed. The extra fields' value columns come next, in the caller's
    names; then the library's own columns. A name that is taken gets ``_`` appended until it is
    free (spec 008, 010). Without a collision every name is the default one.
    """
    taken = set(columns)

    def free(name: str) -> str:
        while name in taken:
            name += "_"
        taken.add(name)
        return name

    value_columns = {name: free(name) for name in fields}
    page = free("page")
    row = free("row")
    grounding: dict[str, str] = {}
    coverage: dict[str, str] = {}
    for column in columns:
        grounding[column] = free(column + GROUNDING_SUFFIX)
        coverage[column] = free(column + COVERAGE_SUFFIX)
    field_grounding: dict[str, str] = {}
    field_coverage: dict[str, str] = {}
    field_source: dict[str, str] = {}
    for name in fields:
        field_grounding[name] = free(name + GROUNDING_SUFFIX)
        field_coverage[name] = free(name + COVERAGE_SUFFIX)
        field_source[name] = free(name + SOURCE_PAGE_SUFFIX)
    return OutputNames(
        page,
        row,
        grounding,
        coverage,
        free("grounding_status"),
        free("recheck_changes"),
        value_columns,
        field_grounding,
        field_coverage,
        field_source,
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
    extra: dict[str, ExtraResult] = field(default_factory=dict)  # extra fields (spec 010)

    @property
    def status(self) -> str:
        """Return the worst status of the row's cells and extra fields."""
        statuses = [c.status for c in self.cells.values()]
        statuses += [r.grounding.status for r in self.extra.values()]
        return max(statuses, key=lambda s: SEVERITY.get(s, 0))


@dataclass
class Flag:
    """A cell that is not an exact match and needs review."""

    page: int
    row: int
    column: str
    status: str
    coverage: float | None
    extra: bool = False  # an extra field of the page, not a cell: `column` is the field's name


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
    # extra fields (spec 010): each page of the table -> field name -> result; the names in column
    # order; and the accepted rechecks, (printing page, name) -> (original, new)
    extra_fields: dict[int, dict[str, ExtraResult]] = field(default_factory=dict)
    extra_names: tuple[str, ...] = ()
    extra_changes: dict[tuple[int, str], tuple[str, str]] = field(default_factory=dict)

    def page_rows(self, page: int) -> list[Row]:
        """Return the rows of one page (1-based)."""
        grounding = self.grounded[page]
        return [
            Row(page, i + 1, values, cells, dict(self.extra_fields.get(page, {})))
            for i, (values, cells) in enumerate(zip(grounding.rows, grounding.cells, strict=True))
        ]

    def rows(self) -> list[Row]:
        """Return every row of the document in page order."""
        return [row for result in self.pages for row in self.page_rows(result.page)]

    def records(self) -> list[dict[str, object]]:
        """
        Return flat rows: page, row, the values, the extra fields, then the groundings.

        Order: ``page``, ``row``, the values, the extra fields' values, each column's grounding
        and coverage, each extra field's grounding, coverage and source page, the row's status
        and the accepted rechecks. A library column whose name is taken gets a trailing ``_``.
        """
        names = output_names(self.columns, self.extra_names)
        out: list[dict[str, object]] = []
        changes: dict[tuple[int, int], list[str]] = {}
        for p in self.proposals:
            if p.outcome == "accepted":
                text = f'{p.column}: "{p.original}" -> "{p.proposed}"'
                changes.setdefault((p.page, p.row), []).append(text)
        for row in self.rows():
            record: dict[str, object] = {names.page: row.page, names.row: row.row, **row.values}
            for name in self.extra_names:
                record[names.fields[name]] = row.extra[name].value if name in row.extra else ""
            for column in self.columns:
                cell = row.cells[column]
                record[names.grounding[column]] = cell.status
                record[names.coverage[column]] = cell.coverage
            row_changes = list(changes.get((row.page, row.row), []))
            for name in self.extra_names:
                got = row.extra.get(name, ExtraResult())
                record[names.field_grounding[name]] = got.grounding.status
                record[names.field_coverage[name]] = got.grounding.coverage
                record[names.field_source[name]] = got.source_page
                if got.source_page is not None and (got.source_page, name) in self.extra_changes:
                    old, new = self.extra_changes[got.source_page, name]
                    row_changes.append(f'{name}: "{old}" -> "{new}"')
            record[names.status] = row.status
            record[names.changes] = "; ".join(row_changes)
            out.append(record)
        return out

    def _frame_columns(self) -> list[tuple[str, Kind]]:
        """Return (name, kind) for every column of `records()`, in order."""
        names = output_names(self.columns, self.extra_names)
        out: list[tuple[str, Kind]] = [(names.page, "int"), (names.row, "int")]
        out += [(column, "str") for column in self.columns]
        out += [(names.fields[name], "str") for name in self.extra_names]
        for column in self.columns:
            out += [(names.grounding[column], "str"), (names.coverage[column], "float")]
        for name in self.extra_names:
            out += [
                (names.field_grounding[name], "str"),
                (names.field_coverage[name], "float"),
                (names.field_source[name], "nullable_int"),
            ]
        return [*out, (names.status, "str"), (names.changes, "str")]

    def to_pandas(self) -> "pandas.DataFrame":
        """Return `records()` as a pandas DataFrame (ints, strings and a float coverage)."""
        import pandas as pd  # noqa: PLC0415

        columns = self._frame_columns()
        dtypes = {"int": "int64", "str": "str", "float": "float64", "nullable_int": "Int64"}
        frame = pd.DataFrame(self.records(), columns=[name for name, _ in columns])
        return frame.astype({name: dtypes[kind] for name, kind in columns})

    def to_polars(self) -> "polars.DataFrame":
        """Return `records()` as a polars DataFrame (ints, strings and a float coverage)."""
        import polars as pl  # noqa: PLC0415

        dtypes = {
            "int": pl.Int64,
            "str": pl.String,
            "float": pl.Float64,
            "nullable_int": pl.Int64,
        }
        schema = {name: dtypes[kind] for name, kind in self._frame_columns()}
        return pl.DataFrame(self.records(), schema=schema)

    def flagged(self) -> list[Flag]:
        """
        Return every cell, and every extra field of a row, whose status needs review.

        A flag for an extra field has ``extra=True`` and the field's name in ``column``; it is
        listed on every row that carries the value, so filtering rows by flag works as for cells.
        """
        flags: list[Flag] = []
        for row in self.rows():
            flags += [
                Flag(row.page, row.row, column, cell.status, cell.coverage)
                for column, cell in row.cells.items()
                if cell.status not in UNFLAGGED
            ]
            flags += [
                Flag(row.page, row.row, name, got.grounding.status, got.grounding.coverage, True)
                for name, got in row.extra.items()
                if got.grounding.status not in UNFLAGGED
            ]
        return flags
