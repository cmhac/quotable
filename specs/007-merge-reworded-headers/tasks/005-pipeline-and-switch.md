# 005 - Run the merge in the pipeline, and the `merge_reworded` argument

Spec: `../spec.md` (Requirements 1, 12, 13; Design / Why after extraction; Tests, the switch).
Depends on: task 004.

## Goal

`extract_tables` merges reworded parts by default, `merge_reworded=False` restores today's
result exactly, and the recheck works on a merged table.

## Steps

1. `recheck.py`: read it before wiring (the spec did not). `recheck_table` builds requests from
   `table.pages`, `table.grounded` and `table.layers`; confirm that a table with pages from two
   wordings, B's keys already renamed, goes through it unchanged, including `_apply` and
   `_regrounded`. If something depends on a single run of pages or on the layouts being
   aligned, fix it here and say so in the report.
2. `extract.py`:
   - `run_pipeline(..., merge_reworded: bool = True)`: after the loop that builds `tables` and
     before `if recheck:`, `if merge_reworded: tables = merge_tables(tables)`. Update the
     docstring.
   - `extract_tables_async(..., merge_reworded: bool = True)` and `extract_tables(...)`,
     keyword-only, after `ocr`. Docstring: what it does, that it makes no request, and that
     `Table.merged` records what was joined.
3. Update the `discover.py` module docstring ("Deliberately left out: merging tables whose
   column names drift...") to say the merge now happens after extraction, in `merge.py`.
4. Tests (`tests/test_extract.py` and `tests/test_entrypoint.py`):
   - the existing suite passes without edits except the signature checks that list arguments;
   - wiring, driven by `run_pipeline` with a fake client whose discovery answers describe two
     parts with reworded headers on a fixture PDF from the "Pipeline" family: one `Table` with
     both parts' rows, `merged` non-empty, rows grounded `exact`. This tests our wiring only;
     whether the real model reports the parts this way is the live check (task 006);
   - the same document with `merge_reworded=False`: two `Table`s, `merged == ()` on both,
     identical to what `run_pipeline` returned before this spec (compare with a result built
     with the merge step patched out, not with a stored copy);
   - a document where nothing merges returns tables equal to the previous output for both
     values of the switch;
   - the recheck runs after the merge: a flagged cell in B's part of a merged table is
     rechecked against its own page's layer and the corrected value lands in the merged table;
   - `extract_tables` and `extract_tables_async` accept `merge_reworded` as a keyword, the
     default is `True` (`inspect.signature`), and a positional use raises `TypeError`.
5. `ruff check`, `ruff format`, `ty check`, `just test`.

## Done when

All offline tests pass, `merge_reworded=False` gives the pre-spec result, and a merged table
survives the recheck.
