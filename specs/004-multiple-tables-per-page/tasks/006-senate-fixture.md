# 006 - Recorded Senate fixture and offline test

Spec: `../spec.md` (Tests, recorded Senate fixture). Depends on: 005.

## Goal

The real two-table page, covered offline, from the model's recorded output.

## Steps

1. Take the recorded model answers for `tests/data/senate_expenditures_paddleocr.pdf` from the
   manual run (the discovery answer, and the extract answers for each table and page, before the
   recheck). They are in the scratch cache of that run; copy them as recorded, do not edit or
   write any by hand. If the scratch cache no longer has them, stop and tell the user: a new
   live run needs their go-ahead (task 008).
2. Store them as `tests/data/senate_expenditures_paddleocr.rows.json` with keys `discovery`
   (the `WindowTables` answer) and `tables` (per table: `label`, and `pages`: page -> rows).
   Add a line to `tests/data/README.md` saying this file is the model's recorded output for that
   PDF.
3. Add a test helper (not the shared `SAMPLES` fixture, whose format is different) that replays
   it: `schema` returns the discovery answer, `extract` returns the rows for the table named in
   the request's column structure and the request's page.
4. Test, `recheck=False`: two tables come back; the summary has 7 rows on page 1 and 4 columns;
   the detail has 36, 62 and 26 rows on pages 1 to 3 and 7 columns; the located bands on page 1
   hold 34 words (summary) and 279 words (detail); the summary has no misplaced cell. These
   numbers came out the same in the manual runs; if one differs when run, report it instead of
   editing the expectation.

## Acceptance

- `just check` passes.
- The fixture is the unedited recorded output, and the README line says so.
