# 007 - Docs

Spec: `../spec.md` (Docs). Depends on: tasks 003 to 006.

## Goal

The documentation matches what was built, with the final rule and thresholds from task 003.

## Steps

1. `README.md`: in "Not handled", replace the sentence about tables whose names change between
   pages: a reworded header is now merged when the checks in the spec all pass (say which in a
   short list, in the words of the final rule), refused otherwise; what is still out of scope
   (names that share no words, a different column count, ambiguous partners). Document
   `merge_reworded` in the arguments, `Table.merged` and `MergedPart` in the result type, and
   the residual risk in one honest paragraph with how to measure it (`merged`) and how to turn
   the step off. Remove any "Not carried over yet" line this makes false.
2. `AGENTS.md`: project state (spec 007 implemented; the live check's outcome, or that it has
   not been run), the file tree (`merge.py`; `tests/fixture_tables.py`, `tests/score_merge.py`),
   the command table (`just score-merge`), the test count. Keep `synthetic.py`,
   `synthetic_cases.py` and `data/synthetic/` as they are.
3. `justfile`: confirm the `synthetic` and `score-merge` recipes have a comment each.
4. Spec files: set the status of `../spec.md` to "implemented", fix the argument-list pointer in
   spec 005 (one line pointing to spec 007's `merge_reworded`), and make sure the spec's results
   section from task 003 matches the final constants in `merge.py`.
5. `just check` (hooks, then the offline tests). Stage specific files only; do not commit
   unless asked.

## Done when

`just check` passes; a reader of the README alone can tell what is merged, what is not, and how
to turn it off; the constants named in the docs equal those in `merge.py`.
