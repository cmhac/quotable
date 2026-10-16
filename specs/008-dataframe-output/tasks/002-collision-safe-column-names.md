# 002 - Collision-safe output column names in `records()`

Spec: `../spec.md` (Requirements 9 and 10; Design / Code, first bullet). Depends on: nothing.

## Goal

`Table.records()` never overwrites a PDF column with a library column, or the other way round,
and never raises. A table with no colliding name produces exactly the keys it produces today.

## Steps

1. `table.py`: add one small function that resolves the output names. Input: `self.columns`.
   Output: the name of `page`, `row`, of `<column>__grounding` and `<column>__coverage` for each
   PDF column, of `grounding_status` and of `recheck_changes`.
   - Start with the set of the PDF column names (they are never renamed).
   - Go through the library columns in output order (`page`, `row`, then for each PDF column
     its grounding and coverage, then `grounding_status`, `recheck_changes`). For each, take its
     default name and append `_` until it is not in the set; add the result to the set.
   - Matching is exact and case-sensitive.
2. `records()` uses the resolved names for its keys, in place of the literals and of
   `column + GROUNDING_SUFFIX` / `column + COVERAGE_SUFFIX`. The order of keys stays: page, row,
   the PDF columns in `self.columns` order as the values appear today, then each column's
   grounding and coverage, then `grounding_status` and `recheck_changes`. Check that the value
   keys still come from `row.values` unchanged (a PDF column is never renamed).
3. `validate_schema` is not touched.
4. Tests (`tests/test_tables.py`, built with `tests/table_builder.py`'s `build_table` and the
   `columns=` argument): a PDF column `page` keeps its text in `page` and the page numbers are in
   `page_`; `grounding_status` keeps its values and the verdict is in `grounding_status_`;
   `Amount` next to `Amount__grounding` gives `Amount__grounding_` for `Amount`'s grounding;
   `page` and `page_` both present give `page__`; `Page` does not collide with `page`; no value
   from the PDF changes; nothing raises; a table with no colliding column has exactly the
   default keys (compare against the literal list).
5. `ruff check`, `ruff format`, `ty check`, `just test`. No existing test is edited.

## Done when

The collision tests pass, every existing `records()` test passes unchanged, and `GROUNDING_SUFFIX`
and `COVERAGE_SUFFIX` are still the only place those two strings are written.
