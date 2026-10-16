# 001 - `MergedPart` and `Table.merged`

Spec: `../spec.md` (Requirement 11, the `merged` field). Depends on: nothing.

## Goal

The result type can say what was joined and why. Nothing else changes: no table is merged yet.

## Steps

1. `table.py`: add a frozen dataclass `MergedPart` next to `Table`:
   - `pages: tuple[int, ...]` - the pages the absorbed part had;
   - `columns: tuple[str, ...]` - the column names that part had before they were renamed;
   - `evidence: dict[str, Any]`, or a small frozen dataclass if the keys are fixed: per-position
     token sets (as sorted tuples), the number of equal positions, the largest x difference in
     points, the dominant shapes, the qualifying cell counts per column and side. Pick the
     dataclass if the fields are stable after task 004; start with the dataclass, since a typed
     audit record is easier for callers to read.
2. `Table.merged: tuple[MergedPart, ...] = ()`, added as the last field (after `ocr_pages`) so
   every existing positional construction keeps working. Update the class docstring: "`merged`
   lists the parts absorbed by spec 007's merge step; empty for a table that was never merged".
3. `__init__.py`: export `MergedPart` (check how `Table` is exported and sort `__all__` the same
   way); update `test_entrypoint.py`'s `__all__` test.
4. Tests (`tests/test_tables.py`): `Table(...)` built the old way has `merged == ()`;
   `MergedPart` is frozen and hashable; `Table` equality and `dataclasses.replace` still work.
5. `ruff check`, `ruff format`, `ty check`, `just test`.

## Done when

All offline tests pass with no edit to an existing test other than the `__all__` one, and
`Table(...)` built by `run_pipeline` is unchanged.
