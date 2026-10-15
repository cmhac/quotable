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
