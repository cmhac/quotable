# 002 - The pair checks as pure functions

Spec: `../spec.md` (Requirements 3 to 9, 14; Tests, the checks as pure functions). Depends on:
task 001 (only for the evidence record; the functions below do not need it).

## Goal

Every check in the candidate-pair rule exists as a small pure function with its own tests, and
the rules the fixture has to decide are parameters, so task 003 can score variants without
editing code.

## Steps

1. New `src/gridkey/merge.py` (module docstring: what the step does, that it makes no model
   request, that any doubt means no merge, and a pointer to this spec). Constants with the
   starting values: `GRID_TOLERANCE = 10.0` (points), `MIN_CELLS = 5`, `SHAPE_SHARE = 0.8`.
2. Header words:
   - `name_tokens(name: str) -> frozenset[str]` using `gridkey.text.tokenize` (a multi-level
     name `x.y` contributes both parts' tokens; read `tokenize` and the way multi-level names
     are written in `discover.py` before choosing how to split them).
   - `compatible(a: frozenset[str], b: frozenset[str]) -> bool`: both non-empty and one is a
     subset of the other.
   - `header_check(a_columns, b_columns) -> HeaderCheck`: a frozen dataclass with the column
     count test, `equal` (positions with equal token sets), `all_compatible`,
     `cross_compatible` (any `i != j` pair compatible, either direction; requirement 6). It
     computes the facts only. Whether `equal` must reach half the positions is *not* decided
     here (that is the provisional rule): `half_equal_ok(check)` is a separate function, so a
     variant can leave it out.
3. Geometry and shape:
   - `qualifying_cells(table: Table, column: str)`: the cells that are non-empty and grounded
     `exact` or `fuzzy` with a `bbox`, over all of the table's pages (look at how
     `FieldGrounding.status` names the statuses before filtering).
   - `grid_positions(table) -> list[float | None]`: per column the median of the cells'
     horizontal centres (`(x0 + x1) / 2`), `None` when there are no qualifying cells.
   - `grid_ok(pos_a, pos_b, tolerance)`: every column differs by at most `tolerance` and the
     order of columns by position is the same on both sides.
   - `cell_shape(value: str) -> str` for `currency`, `percent`, `integer`, `decimal`, `date`,
     `word`, `text`, `other`. Dates are the formats the fixture and the sample PDFs use (read
     `tests/synthetic.py`'s `value` kinds and the shape of the cells in `tests/data/*.rows.json`
     before writing the patterns); document what is recognised.
   - `dominant_shape(values: list[str], share: float) -> str | None`: the shape holding at least
     `share` of the cells, else `None`.
   - `column_facts(table) -> list[ColumnFacts]`: per column the position, the cell count and the
     dominant shape (`None` = unknown). Kept in one place so the evidence record (task 001)
     draws on the same numbers the decision used.
4. `pair_verdict(a: Table, b: Table, *, rules: Rules) -> Verdict`: applies requirements 3 to 9
   in order and returns `ok: bool`, the first failing check's name (`shared_page`, `count`,
   `header`, `half_equal`, `ambiguity`, `grid`, `shape`, `min_cells`) and the evidence.
   `Rules` is a frozen dataclass: `half_equal: bool`, `grid_tolerance`, `min_cells`,
   `shape_share`, with the spec's defaults. A condition that cannot be evaluated (no pages, a
   column empty throughout, fewer than `min_cells`, no dominant shape) fails the pair
   (requirement 9); no function in this module returns a pass on missing data.
5. Tests (`tests/test_merge_checks.py`), on small `Table` objects built from real text layers
   (generate tiny PDFs with pymupdf at test time, or reuse fixture documents; no scripted model
   stands in for anything):
   - token compatibility: subset, equal, disjoint, empty on either side, multi-level names;
   - `header_check`: count mismatch, equal positions counted, cross-compatibility both ways
     (bare "Amount" against "Requested Amount" and "Recommended Amount");
   - `grid_positions` and `grid_ok` at the tolerance edge (exactly 10.0 passes, 10.01 fails) and
     for a swapped column order;
   - `cell_shape` for each shape; `dominant_shape` at 79%, 80% and 81%; `min_cells` at 4 and 5;
   - `pair_verdict`: one test per failure name, one passing pair, and each "unknown" condition
     failing the pair.
6. `ruff check`, `ruff format`, `ty check`, `just test`.

## Done when

All offline tests pass; `merge.py` imports nothing from `extract.py`; every check is reachable
from `pair_verdict`; `rules.half_equal=False` removes only the half-equal check.
