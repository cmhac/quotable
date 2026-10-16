# 003 - `Table.to_pandas()` and `Table.to_polars()`

Spec: `../spec.md` (Requirements 1 to 6 and 8; Design / Code; Tests). Depends on: tasks 001 and 002.

## Goal

A `Table` returns its `records()` as a typed pandas or polars DataFrame.

## Steps

1. `table.py`: one private helper returns the ordered `(output name, kind)` list, `kind` in
   `int | str | float`, from the names task 002 resolves: `page` and `row` are `int`, the PDF
   columns `str`, each `<column>__grounding` `str`, each `<column>__coverage` `float`,
   `grounding_status` and `recheck_changes` `str`. Both methods use it, so order and dtypes are
   defined once.
2. `to_pandas(self) -> "pandas.DataFrame"`: import `pandas` inside the method
   (`# noqa: PLC0415`, as `_paddle.py` does). Build `pandas.DataFrame(self.records(),
   columns=names)`, then cast per kind: `int64`, the default string dtype (`str`, not `object`),
   `float64` (a `None` becomes NaN). The explicit `columns=` is what keeps the columns of a
   zero-row table. Check that the dtypes really come out as listed on an empty table too
   (a cast on an empty frame must not leave `object`).
3. `to_polars(self) -> "polars.DataFrame"`: import `polars` inside the method. Build
   `polars.DataFrame(self.records(), schema={name: dtype})` with `Int64`, `String`, `Float64`
   (a `None` stays null). Check an all-null coverage column and a zero-row table keep their
   dtypes; if a list of dicts with a schema does not behave on an empty list, build from
   column lists instead.
4. Neither method goes through the other library or pyarrow; neither mutates the `Table`; each
   call returns a new frame.
5. Annotations use `TYPE_CHECKING` imports so `ty` sees the return types without importing at
   module level. Add docstrings (ruff `D` is on). If `ty` cannot type the pandas calls, fix the
   call, not the rule set; if it truly cannot, a narrow `# ty: ignore[...]` with a reason.
6. `gridkey.__all__` stays as it is.
7. Tests in a new `tests/test_frames.py`, offline, using `build_table` for hand-made tables and
   `tests/conftest.py`'s `replay` / `extract_tables` for one end-to-end table from a recorded
   sample (as `tests/test_extract.py` does). Everything in the spec's Tests section except the
   collision cases (task 002): columns and order equal to `records()`; every cell equal to the
   `records()` value (null in polars, NaN in pandas); dtypes in both libraries (`"$1,234"`
   survives unchanged, pandas strings are not `object`); `None` coverage; an all-missing
   coverage column still float; a zero-row table; two calls give distinct frames and mutating
   one touches neither the other nor `records()`; a document with two tables gives two frames
   with their own columns; one test that a table with a PDF column named `page` gives a frame
   with `page` (text) and `page_` (numbers) and no duplicate column in either library;
   `import gridkey` does not import `pandas` or `polars` (check `sys.modules` in a subprocess).
8. `ruff check`, `ruff format`, `ty check`, `just test`.

## Done when

All new tests pass, the existing suite passes unchanged, and `ty` and `ruff` are clean.
