# 001 - Discovery models and grouping

Spec: `../spec.md` (Requirements 8, 10, 11; Design, `models.py` and `discover.py`). Nothing
here is used by the pipeline yet.

## Goal

The data shapes the discovery stage returns, and the pure logic that turns window answers into
tables: matching entries to pages by order, validating columns, grouping by column signature.

## Steps

1. `src/gridkey/models.py`: add pydantic models with field descriptions (they are the model's
   instructions, as for the existing ones):
   - `TableInfo`: `label`, `columns: list[Column]` (reuse `Column`: name and description),
     `first_row`, `last_row` (the words of that data row as printed, no separators or
     placeholders for empty cells; a total row that belongs to the table is the last row).
   - `PageTables`: `tables: list[TableInfo]`, top to bottom on the page; empty for a page with no
     table.
   - `WindowTables`: `pages: list[PageTables]`, one per image, in order.
2. New `src/gridkey/discover.py` with pure functions (no requests yet):
   - `signature(columns) -> tuple[str, ...]`: each column name through `gridkey.text.tokenize`,
     joined with spaces.
   - `match_pages(answer: WindowTables, pages: list[int]) -> list[PageTables]`: entries are
     matched to `pages` by order; raises a `PageCountError` (subclass of `ValueError`, internal)
     if the counts differ.
   - A small dataclass `Found` for one table: `label`, `schema: TableSchema`, and
     `rows: dict[int, tuple[str, str]]` (page -> first row, last row), plus
     `add(page, info)`.
   - `merge(found: list[Found], page: int, tables: list[TableInfo]) -> None`: adds each reported
     table to the `Found` with the same signature, or starts a new one (the first appearance
     gives label, column names and descriptions). The list keeps first-appearance order.
   - `validate_found(found: list[Found]) -> None`: raises `ExtractionError` when there is no
     table at all, or a table's columns fail the checks `validate_schema` does today (none,
     blank name, duplicate names). Reuse `validate_schema`; do not copy it. (Move
     `ExtractionError` and `validate_schema` out of `extract.py` into a module both can import
     if needed to avoid a circular import, and keep `extract.py` re-exporting them.)
3. Tests in `tests/test_discover.py`:
   - signature ignores case and punctuation and keeps order;
   - `match_pages` matches by order even when the answer's page numbers are absolute or
     repeated, and raises on a count mismatch;
   - `merge`: same columns on two pages is one table with both pages; different columns are two
     tables in first-appearance order; the first appearance's label and names win;
   - `validate_found`: no tables, no columns, a blank name and duplicate names each raise
     `ExtractionError`; a page that reported no table is fine.

## Acceptance

- New tests pass offline; `just lint`, `just typecheck` and `just test` pass.
- `extract_table` and its behaviour are unchanged by this task.
