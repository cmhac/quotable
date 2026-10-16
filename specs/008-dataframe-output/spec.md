# 008 - Table.to_pandas() and Table.to_polars()

Status: open questions resolved

## Summary

A `Table` hands its result back as `records()`, a list of flat dicts. Nearly every user then
wraps that in a DataFrame. This spec adds two methods that do it, and makes both libraries
normal dependencies:

```python
from gridkey import extract_tables

for table in extract_tables("tables.pdf", model="openai:<model-name>"):
    pdf = table.to_pandas()  # pandas.DataFrame
    pl_df = table.to_polars()  # polars.DataFrame
```

Both frames have the same rows and columns as `table.records()`; they are `records()` with
types, not a second view of the data.

## Motivation

- `records()` is the only output today (README, "Not carried over yet": no CSV writer or CLI).
  Getting from it to a CSV, a join or a filter on `__grounding` takes the same three lines in
  every script.
- `records()` is untyped: coverage is `float | None` in a list of dicts, and a hand-built frame
  from an empty table has no columns at all. The library can get the dtypes and the empty case
  right once.
- Review work is column-oriented ("show me every cell whose status is not `exact`"), which is
  what a frame is for.

## Requirements

1. **`Table.to_pandas() -> pandas.DataFrame`** and **`Table.to_polars() -> polars.DataFrame`**.
   No arguments. Synchronous. One frame per `Table` (a document with several tables gives
   several frames, as it gives several `Table`s; there is no table column, as for `records()`
   in spec 004 requirement 5).
2. **Same content as `records()`.** One row per extracted row, in the same order, with the same
   columns in the same order (names as resolved by requirement 9): `page`, `row`, each value
   column of `Table.columns`, then for each
   value column `<column>__grounding` and `<column>__coverage` (grouped as in `records()`, not
   all groundings first), then `grounding_status` and `recheck_changes`. The frames are built
   from `records()`, so there is one source of truth and a change to `records()` cannot leave a
   frame behind.
3. **Dtypes** (the same in both libraries, in each library's own names):

   | Column                          | Type                                         |
   | ------------------------------- | -------------------------------------------- |
   | `page`, `row`                   | 64-bit integer                               |
   | value columns                   | string, exactly as extracted (no inference)  |
   | `<column>__grounding`           | string                                       |
   | `<column>__coverage`            | 64-bit float; missing is null / NaN          |
   | `grounding_status`, `recheck_changes` | string                                 |

   Value columns stay strings on purpose: grounding compares the text the model returned with
   the text layer, so `"$1,234"` or `"(12)"` must reach the user unchanged. Converting to
   numbers is the user's decision. In pandas the string type is pandas' default string dtype
   (`str` in pandas 3), not `object`. Coverage is missing for cells that were never looked up
   (statuses `empty`, `not_on_page`, `untokenized`, as `FieldGrounding.coverage` is `None`).
4. **A table with no rows** gives a frame with zero rows and all the columns and dtypes above,
   not a frame with no columns.
5. **Neither method mutates the `Table`**, and each call returns a new frame (no shared state
   between calls).
6. **Neither conversion goes through the other library or through pyarrow.** Polars'
   `to_pandas()` needs `pyarrow`, which is not a dependency; each method builds its frame
   directly from `records()`.
7. **pandas and polars are base dependencies**, not extras, as compatible ranges rather than
   exact pins (decision: the library is installed into its own virtual environment, so
   a wider range costs nothing): `pandas>=3,<4` and `polars>=2,<3` (latest on PyPI today:
   3.0.6 and 2.0.0; pandas 3.0.6 is already in `uv.lock` through the dev group's PaddleOCR).
   `uv lock` then `uv sync`; no hand edits to `uv.lock`. The other dependencies stay pinned.
8. **Public surface is unchanged.** The methods live on `Table`; `gridkey.__all__` does not
   change and gridkey exports no pandas or polars names.
9. **No column-name collisions, no errors, no lost data.** The library adds its own columns
   (`page`, `row`, `<column>__grounding`, `<column>__coverage`, `grounding_status`,
   `recheck_changes`) next to the PDF's columns, and a PDF column can have any of those
   names (today `records()` silently overwrites one with the other). The rule, applied in
   `records()` so `records()` and both frames agree:
   - **PDF columns are never renamed.** Their names and values are exactly what the model
     extracted.
   - A library column whose default name is already taken (by a PDF column or by an earlier
     library column) gets `_` appended until the name is free. A PDF column `page` gives the
     library's page number the name `page_`; a PDF column `row` and another `row_` gives `row__`.
   - Nothing raises: `validate_schema` is unchanged and a table with such a column extracts
     normally.
   - With no collision, which is the normal case, every name is exactly the default, so the
     existing `records()` keys, README and tests do not change.
   - Matching is exact and case-sensitive (`Page` does not collide with `page`).
   - Names are unique by construction, so a frame never has a duplicate column.
10. **Behaviour otherwise unchanged:** grounding, prompts, caches and the pipeline are
    untouched. The only change to `records()` is requirement 9, and only for tables that have
    a colliding column name.

## Design

### Code

All in `src/gridkey/table.py`; no new module.

- A name resolver in `table.py` (one small function) implementing requirement 9: given
  `Table.columns` it returns the output name of each library column, taking PDF names first and
  then each library column in output order, appending `_` until the name is unused. `records()`
  uses it for its keys (replacing the inline `column + GROUNDING_SUFFIX` and the literal
  `"page"`, `"row"`, `"grounding_status"`, `"recheck_changes"`), so there is one place that
  decides names.
- A module-level ordered schema derived from the resolved names, used by both frame methods, so
  column order and dtypes are defined once. Something like:

  ```python
  def _frame_columns(self) -> list[tuple[str, str]]:
      """Return (name, kind) for every frame column, kind in int | str | float."""
  ```

- `to_pandas()`: `pandas.DataFrame(self.records(), columns=names)`, then cast by kind. Building
  with explicit `columns=` is what makes the empty case keep its columns. Cast ints to `int64`,
  strings to the default string dtype, coverage to `float64` (a `None` becomes NaN).
- `to_polars()`: `polars.DataFrame(self.records(), schema={name: dtype})` with
  `pl.Int64`, `pl.String`, `pl.Float64` (a `None` stays null). Passing the schema is what makes
  the empty case and an all-null coverage column typed correctly.
- Imports (decision): each method imports its library inside the method body, with
  `# noqa: PLC0415` as `_paddle.py` does, so `import gridkey` loads neither and a pandas user
  does not pay for polars. The annotations use `TYPE_CHECKING` imports so `ty` sees the return
  types. The implementation task measures `import gridkey` before and after and reports it.

### Dependency cost

`pandas` brings `numpy`, `python-dateutil` (and `six`) and, on Windows, `tzdata`. `polars`
brings `polars-runtime-32`, a compiled wheel. None of these is PyTorch-sized, but they are a
real addition to a plain `pip install gridkey`, which until now has had no numpy at all (spec 005
checked this and listed numpy as absent; that check was against PyTorch-class packages and its
"none of numpy" line no longer holds after this spec). The implementation task measures the
before/after: package count, `site-packages` size and `python -X importtime -c "import gridkey"`
and records them in its report. Two doc statements go stale and get fixed (see Docs):
README and spec 006 describe OpenCV and "pandas" as costs of the `ocr` extra.

### Alternatives considered

- **Return only the value columns, or add a values-only flag
  (`to_pandas(include_grounding=False)`).** Rejected (decision): the grounding columns are the
  point of the library, and `df[table.columns]` (pandas) or `df.select(table.columns)` (polars)
  gives the values-only view in one line.
- **Optional extras (`gridkey[pandas]`).** Rejected by the request: base dependencies.
- **A single `to_frame(library=...)`.** Rejected: two methods named for what they return are
  simpler to read and to type-check.
- **Reject colliding names in `validate_schema`.** Rejected (decision): a table with a `page`
  column would be unextractable, after the discovery request was already paid for.
- **Always prefix the library's columns (`_page`, `_row`, ...).** Rejected: changes every
  `records()` key for the sake of a rare case, and a prefix can collide too. Requirement 9
  leaves the normal case untouched.
- **Rename the PDF's column instead.** Rejected: the PDF's names are the user's data, and
  `Table.columns` would stop matching the frame.
- **Converting numeric-looking columns to numbers.** Rejected, see requirement 3.

## Out of scope

- CSV, Excel or Parquet writers, and a CLI (the frames make a CSV one call away:
  `table.to_polars().write_csv(path)`).
- Number or date parsing of value columns.
- Concatenating the frames of several tables, or adding a `table`/`label` column.
- Lazy frames (`polars.LazyFrame`), pandas index choices (the default `RangeIndex` is used).
- Rejecting reserved names in `validate_schema`, or prefixing every library column
  (considered and rejected, see Alternatives).
- Exposing the resolved name mapping as an API; the names are visible in `df.columns` and the
  rule is documented.

## Tests

All offline; new file `tests/test_frames.py`, using the existing `tests/conftest.py` fakes and the
recorded sample rows (as `tests/test_extract.py` does).

- Collisions (both libraries and `records()`): a table with a PDF column `page` keeps its text
  in `page` and the page numbers are in `page_`; a column `grounding_status` keeps its values and
  the library's verdict is in `grounding_status_`; a column `Amount__grounding` next to `Amount`
  keeps its values and `Amount`'s grounding is `Amount__grounding_`; `page` and `page_` both
  present gives `page__`; no frame has a duplicate column; no value from the PDF is changed;
  nothing raises; `Page` does not collide with `page`; a table with no colliding column has
  exactly the default names.
- Columns and order: `list(df.columns)` equals `list(records()[0])` for both libraries.
- Content: for both libraries, every cell equals the `records()` value (missing coverage is
  null in polars and NaN in pandas).
- Dtypes: `page` and `row` are integers, value columns are strings (a value like `"$1,234"`
  survives unchanged), coverage is float, in both libraries; pandas value columns are not
  `object`.
- A cell with `None` coverage (an `empty` cell) is null/NaN, and the coverage column is still
  float when every value in it is missing.
- A table with zero rows (built directly from `Table(columns=[...], pages=[], ...)`) gives a
  zero-row frame with every column and the right dtypes, in both libraries.
- Two calls return distinct frames; mutating one changes neither the other nor
  `table.records()`.
- A document with two tables gives two frames with their own columns.
- `gridkey.__all__` is unchanged; `import gridkey` still works.
- `just check` passes (ruff, ty, the offline suite). The test count in `AGENTS.md` is updated.

Not verifiable offline and not needed: the live model path (nothing here calls a model).

## Docs

- `README.md`: a sentence on column names: a PDF column is never renamed, and a library column
  whose name is taken gets a trailing `_`; the opening example gains `table.to_pandas()` / `table.to_polars()`; the install
  note says both are included; "Not carried over yet / Output" points at the frames as the
  way to write a CSV (still no writer or CLI); the OCR paragraph no longer lists pandas as an
  OCR cost.
- `AGENTS.md`: project state (spec 007), the `table.py` line in the file tree, the test count.
- `specs/006-paddleocr-fallback/spec.md` is history and is not rewritten; the README is the
  place the stale "pandas" note is fixed.
- Status of this spec set to implemented only after the user approves the change.

## Open questions

All resolved (user):

1. Imports happen inside each method (Design / Code).
2. Compatible ranges instead of exact pins (requirement 7). The stated reason ("conflicts
   aren't a problem in a virtual environment") could also read as a reason to keep exact pins;
   the ranges reading was applied. Confirm.
3. No values-only flag (Alternatives considered).
4. Column-name collisions are handled without raising and without overwriting anything. The
   mechanism (trailing `_` on the library's column, PDF columns untouched, requirement 9) was
   chosen by the agent among ways of meeting that; say so if you want a different one, such as
   always-prefixed library columns.
