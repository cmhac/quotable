# 004 - `extract_tables`: the new API for the one-table-per-page case

Spec: `../spec.md` (Requirements 1-6, 14-17). Depends on: 002, 003.

## Goal

Replace `extract_table` with `extract_tables`, driven by the new discovery, producing one
`Table` per discovered table. This task covers documents where each page holds at most one
table (including several tables on different pages); multi-table pages come in task 005.

## Steps

1. `src/gridkey/extract.py`:
   - Rename `extract_table_async` and `extract_table` to `extract_tables_async` and
     `extract_tables`; return `list[Table]`. Remove `schema_pages`, `SCHEMA_PAGES` and
     `SCHEMA_PROMPT`; add `discovery_pages: int = DISCOVERY_PAGES` to both, keeping the two
     signatures identical.
   - Order: text-layer check, render, `discover`, then per table:
     `page_layouts(columns, [uncropped layers of the table's pages])`, extraction of the table's
     pages with `extract_page` (concurrency limit as now, shared across tables),
     `ground_document` with the table's columns, pages and layers, `Table(...)`, then
     `recheck_table` when `recheck`.
   - Update the module docstring (steps 1 and 2 of the pipeline).
2. `src/gridkey/table.py`: `Table.label: str = ""`.
3. `src/gridkey/__init__.py`, the `README.md` example, `tests/live/test_live_extraction.py` and
   the existing tests use the new names. No alias for the old names.
4. Test helpers: `tests/conftest.py` `replay` answers the `schema` stage with a `WindowTables`
   built from the sample's columns, one table per page (first and last row text taken from the
   sample's first and last recorded rows' values joined), with one entry per image in the
   request.
5. Update `tests/test_extract.py` and `tests/test_recheck.py`:
   - the stage list becomes `["schema", *["extract"] * pages]` for documents within one default
     window;
   - `test_schema_discovery_sees_only_the_first_pages` becomes a test that every page is seen:
     with `discovery_pages=2` on `fy22_ag_house_original` there are two discovery requests of two
     images each;
   - the signature-equality test covers the new parameters;
   - every assertion about rows, grounding, retries, rechecks and `TextLayerError` keeps its
     meaning and passes (the results are `tables[0]`).
6. New tests:
   - a document with two different tables on different pages returns two `Table`s in order of
     first appearance, each with only its own pages in `pages`, `layers`, `grounded`, `layouts`;
   - `Table.label` is the first-appearance label;
   - a headerless continuation page joins its table and gets an inherited layout;
   - a document with no table raises `ExtractionError`;
   - `max_requests` counts the discovery requests.

## Acceptance

- `just check` passes.
- No reference to `extract_table(` (singular) or `schema_pages` remains outside `specs/001`-`003`
  and this spec.
