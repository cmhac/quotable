# 001 - The position check keeps its areas

Spec: `../spec.md` (Requirement A5; C5 highlights "Row window", "Column range", "Cell area").
Depends on: nothing.

## Goal

`check_positions` keeps the row windows and column ranges it fits, on each page's
`PageGrounding`, so a run can store them. Its verdicts and counts do not change.

## Steps

1. Red first: a test in `tests/steps/test_position.py` that runs `check_positions` on a fixture
   document (one of `tests/data/synthetic/`, through `ground_document`) and expects every row
   with an anchor to have a window and every banded column to have a range; and a test that the
   statuses and counts of every fixture document are the same as before (record them first by
   running the current code, then compare).
2. `steps/position.py`: `PageGrounding` gains two fields with empty defaults:
   `row_windows: dict[int, Window]` (0-based row index -> `(y0, y1)`, the windows
   `_row_windows` fitted) and `column_ranges: dict[str, Window]` (column -> `(x0, x1)`, from
   `_regions(bands)`; a column without enough evidence is absent). `check_positions` fills them
   on each page after fitting. No other behaviour changes.
3. The recheck re-grounds through `ground_document`, so the areas are fitted again for the
   final table; check that `recheck_table`'s result carries them (a test with a fake client).
4. `ruff check`, `ruff format`, `ty check`, `just test`.

## Done when

Every page of every table carries its areas, the statuses and counts of the whole fixture are
unchanged, and the suite passes untouched.
