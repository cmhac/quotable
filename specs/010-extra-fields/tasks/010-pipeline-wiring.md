# 010 - Wire it into `extract_tables`

Spec: `../spec.md` (Requirements 3, 13, 18; Design / Code: `extract.py`). Depends on: tasks 004 to
009.

## Goal

`extract_tables(..., extra_fields=...)` runs the whole feature in the documented order and returns
tables with the fields attached.

## Steps

1. Read `extract.py` (`run_pipeline`, `extract_tables_async`, `extract_tables`, `usable_layers`) and
   `tests/conftest.py`'s `replay` / `extract_tables` helpers first.
2. Add `extra_fields: ExtraFields | None = None` to `extract_tables_async`, `extract_tables` and
   `run_pipeline`. Call `validate_extra_fields` first, before any request or OCR (the fake client
   must have seen nothing when it raises).
3. Order (requirement 13): discovery with the fields, ground the values on the layers from
   `usable_layers` (so OCR'd text counts), field recheck, missed-header check and second look,
   `propagate`, then attach to the tables (`Table.extra_fields`, `Row.extra`) before the existing
   merge and cell recheck run, so a merged table gets an entry per page. Check where in
   `run_pipeline` attaching is simplest and say why in a comment.
4. Without `extra_fields`, nothing in the pipeline changes: same requests, same cache keys, same
   output (a test pins this by replaying an existing recorded sample and comparing).
5. Log at INFO under the `quotable` logger: fields read, pages carried, suspect pages, second-look
   requests (requirement 18).
6. Tests in a new `tests/test_extra_fields_pipeline.py`, driven by `run_pipeline` with fake clients:
   the Senate sample with `carry_forward=True` (pages 2 and 3 carry the page 1 values, `source_page`
   1) and with the default (pages 2 and 3 empty); every `extra-*` fixture document end to end
   against its truth; a bad request raises before any model call; `max_requests` counts the second
   looks; a document with OCR'd pages; two tables on one page get the same entry.
7. `ruff check`, `ruff format`, `ty check`, `just test`.

## Done when

The Senate sample and every `extra-*` document produce the truth's values through the public path
with fake clients, the unchanged-output test passes, and the checks are clean.
