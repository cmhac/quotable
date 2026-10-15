# 002 - Discovery windows with carry-forward

Spec: `../spec.md` (Requirements 3, 7, 9, 11, 17; Design, `discover.py`). Depends on: 001.
Not wired into `extract_table` yet.

## Goal

An async `discover(images, client, *, discovery_pages) -> list[Found]` that inventories every
page in sequential windows, carrying the tables found so far into each next request.

## Steps

1. In `src/gridkey/discover.py` add `DISCOVERY_PAGES = 4` and the prompt `DISCOVER_PROMPT`.
   Keep the wording from the experiments (it is what was tested): list every distinct table
   on each page, top to bottom, with its columns as printed (multi-level headers
   `<level1>.<level2>`, wrapped header text joined by one space, page titles and numbers
   ignored); the words printed on the first and last data row of the table on that page, "no
   separators and no placeholders" for empty cells; a total row that belongs to the table is its
   last row; answer for every image in order. The scratch `exp1_inventory_prompt.py` and
   `exp_inv.py` hold the tested text.
2. A second constant `CARRY_PROMPT`, appended when tables are already known: a page may continue
   a known table without printing its header again, then report it with exactly the known
   column names; never invent columns for a table whose header cannot be seen; a new table with
   its own header is reported with the columns printed in it.
3. `discover`:
   - raises `ValueError` if `discovery_pages < 1`;
   - for each window of `discovery_pages` consecutive page images, in order and one after the
     other, sends `Request("schema", prompt, WindowTables, parts)` where `parts` are the
     window's `Image`s, plus (after the first window) a text part `Known tables:` followed by
     one line per known table: number, pages, column names;
   - matches the answer to the window's pages with `match_pages`; on `PageCountError` repeats
     the request once with the problem named (and the previous output, as `retry_prompt` does);
     a second failure raises `ExtractionError`;
   - merges each page's tables with `merge`, then returns the `Found` list after
     `validate_found`.
4. Tests in `tests/test_discover.py` (FakeClient, canned `WindowTables` answers):
   - default window is 4: a four-page document makes one request with four images;
   - `discovery_pages=2` on four pages makes two requests, in order, never concurrently (assert
     the second request is only made after the first answered), with two images each;
   - the first request has no known-tables part; the second has it, listing the first
     request's tables (assert on the text);
   - a headerless continuation answer (known columns reported for a later page) gives one table
     over all pages;
   - a count mismatch is retried once and then raises `ExtractionError`;
   - a count mismatch followed by a good answer succeeds with two requests;
   - `discovery_pages=0` raises `ValueError`;
   - prompt tests: the key phrases above are in the prompts.

## Acceptance

- New tests pass offline; `just lint`, `just typecheck` and `just test` pass.
- No live requests are made in this task.
