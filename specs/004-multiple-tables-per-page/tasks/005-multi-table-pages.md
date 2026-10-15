# 005 - Pages with more than one table

Spec: `../spec.md` (Requirements 12, 13, 15). Depends on: 003, 004.

## Goal

On a page that holds two or more tables, each table is extracted with a request that names the
others, and is grounded, position-checked and rechecked against only its own band of the text
layer.

## Steps

1. `src/gridkey/extract.py`:
   - Call `table_layers` (task 003) for each page that more than one table is on; use the
     result as that table's layer for that page in `Table.layers`, `ground_document` and (via
     `Table.layers`) `recheck_table`. Pages with one table keep the whole page layer.
   - `layouts` still come from the uncropped layers (requirement 14).
   - `extract_page` takes an optional list of the other tables on the page (label and column
     names). With it, the prompt is `EXTRACT_PROMPT` plus `MULTI_TABLE_SENTENCE` (this page holds
     more than one table; extract ONLY the table whose columns are listed in the column
     structure; do not return rows of the other table(s) named below) and the request has an
     extra text part `Other tables on this page:` with one line per other table. Without it, the
     request is exactly what it was.
   - The retry rule is unchanged and reuses the same prompt and parts.
2. `recheck.py`, `grounding.py` and `position.py` are not changed (the recheck sends
   `table.layers[page].lines()`, which is now the band).
3. Tests with a synthetic two-table page (`make_pdf`) and a fake client:
   - two `Table`s come back; each table's `layers[page]` holds only its own words;
   - the extract request for each table includes the sentence and the other table's label and
     columns; a single-table page's request has neither (compare the parts with task 004's);
   - a value that exists only in the other table is `ungrounded` in this one (no cross-match);
   - a shared word (a header word that appears in both tables) does not make the position check
     see the other table's rows;
   - the recheck request for a flagged cell contains the table's own band's text lines and none
     of the other table's;
   - when the band cannot be isolated (task 003's errors) the run raises `ExtractionError`
     before any extract request is made.

## Acceptance

- `just check` passes.
- Documents with at most one table per page behave exactly as after task 004 (existing tests
  unchanged).
