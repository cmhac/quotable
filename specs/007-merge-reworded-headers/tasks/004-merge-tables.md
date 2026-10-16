# 004 - `merge_tables`: uniqueness and building the merged `Table`

Spec: `../spec.md` (Requirements 1, 2, 10, 11, 12; Design / Module and code; Tests, must merge,
must not merge, merged table contents). Depends on: tasks 001, 002 and 003 (the rules and
constants it uses are the ones task 003 settled).

## Goal

`merge_tables(tables: list[Table], *, rules: Rules = DEFAULT_RULES) -> list[Table]` joins the
pairs that pass and returns everything else untouched.

## Steps

1. `merge.py`:
   - `DEFAULT_RULES`: the settled rules from task 003.
   - `candidate_pairs(tables, rules)`: all index pairs `(i, j)` that pass `pair_verdict`, with A
     the table whose first page is smaller. Decided on the original tables only.
   - Mutual uniqueness (requirement 10): a pair merges only if each table is in exactly one
     candidate pair. A table in two or more pairs merges with nobody, and so do those partners.
   - `merge_pair(a, b, verdict) -> Table`, per requirement 11:
     - `columns` from A; B's row keys renamed to A's names by position in every `PageResult`
       (including `absent`); pages sorted by page number;
     - `layers` union (disjoint by the no-shared-page check);
     - `layouts` aligned to the sorted pages, B's `PageLayout` column names renamed the same
       way (read `PageLayout` in `layout.py` for what carries names);
     - `grounded` and `position` recomputed with `ground_document(columns, pages, layers)`;
     - `label` from A; `ocr_pages` the sorted union; `proposals` empty (the recheck has not
       run); `merged` = A's own `merged` plus one `MergedPart` for B, with the evidence from
       the verdict.
   - Position order of the output: each merged table stands where A stood; the rest keep their
     order. Only one pair can merge per table (uniqueness), so no chain handling is needed;
     say so in a comment.
2. If no pair passes, return the input list itself unchanged (same objects, same order), so
   requirement 12 can be tested by identity.
3. Tests (`tests/test_merge.py`), on `Table`s built from real text layers (task 003's
   `fixture_tables` is usable here, plus small PDFs made with pymupdf at test time):
   - must merge: the reworded two-column case; "Amount Requested" vs "Requested Amount"; the
     pages come out in page order, B's keys are renamed, `columns` are A's, `layouts` line up
     with `pages`, `position` covers the whole table, `merged` has one entry with the evidence;
   - must not merge, one test each: shared page; different column count; headers contained but
     too few equal (as the chosen rule has it); the ambiguous bare "Amount" next to both
     "Requested Amount" and "Recommended Amount"; same words on a shifted grid; compatible
     headers with different value shapes; too few cells; no dominant shape; three mutually
     compatible tables (none merges); the interleaved A / B / A case;
   - nothing merges: the returned list `is` the input list; the tables are the same objects;
   - a fixture sweep: for every fixture relation with `stage == "merge"` and a settled
     `expect_merge`, `merge_tables` on the two parts' tables merges exactly when expected
     (parametrised over the manifest). Relations with `expect_merge: null` are not asserted
     here (task 003 scores them).
4. `ruff check`, `ruff format`, `ty check`, `just test`.

## Done when

All offline tests pass, the fixture sweep passes for every settled relation, and a list with
no passing pair comes back as the same list.
