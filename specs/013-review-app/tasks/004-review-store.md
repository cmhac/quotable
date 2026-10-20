# 004 - Verdicts and drafts in `.quotable/review/`

Spec: `../spec.md` (Requirements D4, D5, D6, D8, D9, F1 to F5). Depends on: task 002.

## Goal

A standard-library module, `quotable/review/verdicts.py` (the new `quotable/review/`
subpackage starts here), that stores verdicts and drafts and says which verdict applies to a
cell of a run. No server yet.

## Keys

- A cell: `(sha256, columns, page, row, column)`. The table's columns identify it within a
  document (discovery keeps one table per column set), so the key survives a re-run that
  returns the tables in another order.
- An extra field: `(sha256, "extra", name, printing page)`, shared by every table and row that
  carries the value (D9).
- A key is written to the files as a JSON object with those fields, never as a joined string.

## Steps

1. Red first: tests in `tests/review/test_verdicts.py` (step 5).
2. `storage.py`: `REVIEW_DIR_NAME = "review"` and `review_dir(project_dir)`.
3. `verdicts.py`:
   - `CATEGORIES`: the nine error categories with their descriptions, in the spec's order (the
     order gives the keys 1 to 9).
   - `Verdict` (frozen dataclass, the fields of F2) with `to_line()` / `from_line()`, and
     `validate(...)`: verdict in `correct | changed | unsure`; for `changed` a category from
     `CATEGORIES` and a value different from the extracted one; note and value at most 5,000
     characters. Raises `ValueError` with a message the app can show.
   - `VerdictStore(project_dir)`: `append(verdict)` writes one line with one `os.write` on an
     `O_APPEND` file (as `CostLog` does); `latest()` reads the file and returns key -> latest
     verdict (by file order), skipping damaged lines and counting them; `apply(key, value)`
     returns `("reviewed", verdict)`, `("stale", verdict)` when the latest verdict judged a
     different value (D8), or `("none", None)`.
   - `DraftStore(project_dir)`: `get(key)`, `put(key, note, value, category)` with `saved_at`,
     `clear(key)`; the whole file is rewritten with `write_atomic` under a `threading.Lock`.
     A damaged `drafts.json` is treated as empty and kept aside as `drafts.json.bad`.
   - Folders are created on the first write only.
4. Nothing here imports the server, pandas, polars or pymupdf.
5. Tests: append and `latest` with two verdicts for one key (the later wins) and one damaged
   line (skipped, counted); `apply` for same value, different value (stale), no verdict;
   an extra-field key applies to two rows and two tables of the same run; a re-run whose tables
   come in another order still finds the verdicts; `validate` refuses each bad input of D4 and
   F4; drafts round trip, clear, and survive a damaged file; two threads appending 200 lines
   each give 400 whole lines.
6. `ruff check`, `ruff format`, `ty check`, `just test`.

## Done when

Verdicts and drafts round trip, the D8 matching and staleness rules hold, and the suite passes.
