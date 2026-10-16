# 009 - Output: `Row.extra`, `Table.extra_fields`, columns, frames, status and flags

Spec: `../spec.md` (Requirements 14 to 17; Design / Code: `table.py`). Depends on: tasks 005 and
008.

## Goal

The fields appear on every `Row`, in `Table.extra_fields`, in `records()` and in both frames, and
count like any grounded text.

## Steps

1. Read `table.py` (`Row`, `Table`, `Flag`, `output_names`, `records()`, the frame helper) and
   `tests/test_frames.py`, `tests/table_builder.py` first. Spec 008's column rules are the base.
2. `Row.extra: dict[str, ExtraResult]` (default empty, so existing constructors keep working) and
   `Table.extra_fields: dict[int, dict[str, ExtraResult]]` keyed by the table's pages. A table of
   several pages or made by the spec 007 merge has an entry per page; two tables on one page get
   the same entry.
3. `records()` and the frames: column order `page`, `row`, values, field values, per-value
   grounding and coverage, per-field `<name>__grounding`, `<name>__coverage`, `<name>__source_page`
   (integer; null when missing; `Int64` in pandas, `Int64` in polars), `grounding_status`,
   `recheck_changes`. Without extra fields the columns are exactly today's.
4. `output_names`: PDF columns are never renamed; field columns take the caller's names, with a
   trailing `_` appended until free if a PDF column has the name; the library's own columns take a
   trailing `_` when taken (a field called `page` keeps its name, the page number becomes `page_`).
   Nothing raises. Extend the single place that defines order and dtypes so both frames share it.
5. Status and flags (requirement 17): `Row.status` and `grounding_status` are the worst status over
   the cells and the extra fields (via `SEVERITY`); `flagged()` lists a flag for an extra field on
   every row that carries the value, marked as an extra-field flag (add a marker to `Flag`);
   `recheck_table` ignores these flags. An accepted field recheck (task 008) appears in
   `recheck_changes` of each row that carries it as `<name>: "old" -> "new"`.
6. Tests in `tests/test_frames.py` and `tests/test_extra_fields.py` using `build_table`: `Row.extra`
   and `Table.extra_fields`; column order and names; the collision rule (a field named like a PDF
   column; a field named `page`); dtypes in pandas and polars including the nullable source page;
   tables sharing a page; a merged table; a table with no rows; an ungrounded field makes
   `Row.status` and `grounding_status` `ungrounded` on every row that carries it and shows in
   `flagged()`; the cell recheck does not touch it; the existing frame and table tests pass
   unchanged.
7. `ruff check`, `ruff format`, `ty check`, `just test`.

## Done when

A hand-built table with extra fields gives the documented columns in `records()`, pandas and
polars, and all earlier tests still pass.
