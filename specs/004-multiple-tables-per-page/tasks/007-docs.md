# 007 - Docs

Spec: `../spec.md` (Docs). Depends on: 005 (can run alongside 006).

## Steps

1. `README.md`: the example calls `extract_tables` and loops over the returned tables; the
   Schema discovery row of the stage table becomes discovery of all pages in windows
   (`discovery_pages`, default 4), with the tables found so far carried forward; add a short
   "Not handled" section: side-by-side tables, merging tables whose columns drift between pages,
   and the `ExtractionError` when a table's part of a page cannot be isolated.
2. `AGENTS.md`: project state (spec 004 implemented; `extract_tables`; test count), file
   structure (`discover.py`, and `regions.py` if created). The history note for specs 001 and
   002 stays as it is.
3. Check the module docstrings in `extract.py`, `discover.py` and `table.py` for stale
   statements about "the" table or the first pages.

## Acceptance

- `just check` passes.
- A search for "first five pages", "schema_pages" and "extract_table(" in `README.md`,
  `AGENTS.md` and `src/` finds nothing.
