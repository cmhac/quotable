"""Structured outputs requested from the model."""

from pydantic import BaseModel, Field


class Column(BaseModel):
    """One table column as reported by schema discovery."""

    name: str = Field(
        description=(
            "Column name. Multi-level headers as '<level1>.<level2>' (top "
            "level first). Use the header text as printed."
        )
    )
    description: str = Field(description="What the column contains, with a short example value.")


class TableSchema(BaseModel):
    """Column structure of the table."""

    columns: list[Column] = Field(description="Columns in left-to-right order.")
    notes: str = Field(
        default="", description="Anything unusual about the table layout (merged cells, ...)."
    )


class TableInfo(BaseModel):
    """One table found on one page by discovery."""

    label: str = Field(description="Short name for the table, e.g. its title or what it lists.")
    columns: list[Column] = Field(description="Columns in left-to-right order.")
    first_row: str = Field(
        description=(
            "The words printed on the first data row of this table on this page (not the "
            "header), in reading order, separated by single spaces. Copy only printed words: "
            "no separators and no placeholders for empty cells."
        )
    )
    last_row: str = Field(
        description=(
            "The words printed on the last data row of this table on this page, written the "
            "same way. A total or subtotal row that belongs to the table is its last row."
        )
    )


class PageTables(BaseModel):
    """Every table on one page."""

    tables: list[TableInfo] = Field(
        description="The distinct tables on the page, top to bottom; empty if there is none."
    )


class WindowTables(BaseModel):
    """Every table on each page of a window of consecutive pages."""

    pages: list[PageTables] = Field(
        description="One entry per page image, in the order the images were given."
    )


class PageRows(BaseModel):
    """Rows extracted from one page."""

    rows: list[dict[str, str]]


class CellRecheck(BaseModel):
    """The re-checked value of one cell."""

    row: int = Field(description="Row number as given in the list.")
    column: str = Field(description="Column name exactly as given in the list.")
    value: str = Field(
        description=(
            "The cell's text exactly as printed on the page; repeat the previous "
            "value unchanged if it was already right."
        )
    )


class PageRecheck(BaseModel):
    """Re-checked values for the listed cells of one page."""

    cells: list[CellRecheck]
