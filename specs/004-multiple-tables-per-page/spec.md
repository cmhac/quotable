# 004 - Multiple tables per document

Status: open questions resolved

## Summary

`extract_table` assumes a PDF holds one table. This spec makes the pipeline find every table in
the document, including pages that hold more than one, and extract and ground each of them.
`extract_table` becomes `extract_tables` and returns a list of `Table` objects, one per table.

To do that, schema discovery stops looking at the first few pages only. It becomes an inventory
of all pages, taken in windows of consecutive pages, in which the model lists every table on each
page. Tables with the same columns on different pages are one table. On a page that holds more
than one table, each table is extracted from its own part of the page and checked against only
that part's text layer.

## Motivation

Page 1 of `tests/data/senate_expenditures_paddleocr.pdf` has a four-column summary table
(`DESCRIPTION`, `NET FUNDS AVAILABLE AS OF 04/01/2018 ($)`, `NET EXPENDITURES FOR THE PERIOD OF
04/01/2018 THRU 09/30/2018 ($)`, `TOTAL FUNDING YTD ($)`) above the long seven-column
expenditure-detail table that continues on pages 2 and 3. Today:

- Schema discovery sends the first `SCHEMA_PAGES = 5` page images in one request and gets one
  column list back. It never sees later pages, and it describes only one table. The summary
  table is silently dropped, and nothing reports that it was.
- Even with the right columns, one table per document would be wrong: a page's rows are checked
  against the whole page's text layer, so words shared by two tables (`DESCRIPTION`, amounts)
  would cross-match during grounding and the position check.

Experiments on this document and on the three House fixtures (scratch scripts, about 45 live
requests; nothing in the repo):

| Question | Result |
|---|---|
| Does a per-page inventory find the second table? | Yes. Page 1 gave 2 tables, pages 2 and 3 gave 1 each, in 3 of 3 trials. Batching all 3 pages in one request gave the same in 2 of 2 trials. |
| Does it invent tables? | No. The three House fixtures gave one table per page. The total rows on Senate page 3 stayed in the detail table every time. |
| Is a page-by-page inventory safe on pages without a printed header? | **No.** On `fy22_ag_house_original.pdf`, pages 2 and 4 print no header. Asked about each page alone, the model invented columns (`Program`, `Applicant`, `State`, `Member`) instead of the real `Account`, `Recipient`, `Location`, `Requestor(s)`. Asked about all 4 pages together (2 of 2 trials), or one page at a time with the tables found so far included in the request (windows of 1 and 2 pages), it gave the one correct column set on every page. |
| Does a window of 1, 2 or 3 pages find the same tables on Senate? | Yes: 2 tables, the 7-column one on all 3 pages, the 4-column one on page 1. |
| Can the part of the page that holds one table be found in the text layer? | Yes. The model reports the first and last data row of each table as printed; those are looked up in the text layer. Page 1 split into 34 words (summary), 279 words (detail) and 41 words of titles and headers, identically from two independent discovery runs. |
| Do both tables extract and ground? | Yes, in two end-to-end runs. Summary: 7 rows, 17 cells `exact`, 11 `empty`, none misplaced, identical output in both runs. Detail: 36, 62 and 26 rows (the same as the single-table run); 369 and 370 cells `exact`, none or one misplaced (a page-3 total row that the single-table run also flagged), recheck outcomes as in spec 002. |
| Does each table find its own header (`page_layouts`)? | Yes, run offline on the full page layers: the summary table finds a header on page 1, the detail table on pages 1 to 3. |

The scratch prototype is not part of this spec's code; the Design section says what is taken from
it.

## Requirements

### API

1. **Rename and return type.** `extract_table` is renamed `extract_tables` and
   `extract_table_async` is renamed `extract_tables_async`. Both return `list[Table]`, one
   `Table` per distinct table in the PDF. A PDF with one table returns a list of one.
2. **No shim.** The old names are removed, not aliased. The project has never been published
   (same decision as spec 003). `__init__.py`, the README example, the live test and the tests
   use the new names.
3. **Parameters.** `schema_pages` is removed. `discovery_pages: int = DISCOVERY_PAGES` (module
   constant, 4) is the number of consecutive pages sent in one discovery request. The caller can
   change it per call; values below 1 raise `ValueError`. `recheck: bool = True` is
   unchanged. The sync and async functions keep identical parameters.
4. **Order.** Tables are returned in order of first appearance: by page, then top to bottom on
   the page.
5. **`Table`.** `Table` gains `label: str` (the model's short name for the table, for the
   caller's use; it plays no part in matching). `Table.pages`, `layers`, `grounded` and `layouts`
   cover only the pages the table is on, and `layouts` stays aligned with `pages`. `records()`,
   `rows()`, `page_rows()` and `flagged()` are unchanged and work per table. `records()` gets no
   table column; the caller who concatenates tables uses `Table.label`.
6. **Text-layer check first.** `check_text_layers` still runs before any rendering or request,
   and `TextLayerError` behaves as before.

### Discovery

7. **All pages, in windows.** Pages are sent in order, `discovery_pages` at a time, one request
   per window, one window after another (not concurrently), so that each request can include the
   tables found so far. The request stage name stays `schema`.
8. **What the model returns.** For each page of the window, in order, the list of distinct
   tables on it, top to bottom. For each table: a short label; its columns (name and a
   description with a short example value, as today; multi-level headers as
   `<level1>.<level2>`); the words of its first data row and of its last data row on this page,
   as printed, with no separators or placeholders for empty cells (an earlier wording produced
   `|` for empty cells and that text would not be found in the text layer). A total row that
   belongs to the table counts as its last row.
9. **Headerless continuation pages.** The prompt tells the model that a page may continue a
   table without printing its header again, that it must then report that table with the same
   columns as the known table, and that it must never invent columns for a table whose header it
   cannot see. Windows after the first include a text part listing the tables found so far
   (number, pages, column names), and tell the model to reuse those column names exactly when a
   page continues one of them.
10. **Same table across pages.** Two reported tables are the same table when their column names
    are equal after tokenizing each name with `gridkey.text.tokenize` (so case and punctuation
    do not matter), in the same order. The first appearance gives the table its column names,
    descriptions and label. A document where this rule gives no table at all, or a table whose
    columns are unusable (none, blank, duplicates, as `validate_schema` checks today), raises
    `ExtractionError`. A page with no table (a cover page) is fine.
11. **Page order, not page numbers.** The answer's entries are matched to the window's pages by
    their order, not by the page numbers the model writes (with a one-page window the model
    wrote absolute page numbers that were out of range). If the number of entries differs from
    the number of pages in the window, the request is repeated once with the problem named; a
    second failure raises `ExtractionError`.

### Extraction and checking

12. **The table's part of the page.** On a page with one table, the table's text layer is the
    whole page layer, as today. On a page with two or more tables, a table's layer is the page
    layer cropped to the band from the top of its located first row to the bottom of its located
    last row, 4 pt of margin each side, across the full page width (`Layer.crop`). A row is
    located by looking its text up in the page's text layer with the existing candidate search
    (`grounding.find_candidates`); the topmost match is used for a first row and the bottommost
    for a last row. If a table's first or last row is not found, or the bands of two tables on
    the page overlap, `ExtractionError` is raised, naming the page, the table's label and which
    row was not found or which tables overlap. There is no fallback: a table whose own text cannot
    be isolated would be checked against the other table's words, which is the failure this spec
    removes, and silently weaker checking is not wanted.
13. **Extract requests.** A table on a single-table page is extracted with the existing
    `extract_page` request: `EXTRACT_PROMPT`, the column structure, the page image. A table on a
    multi-table page uses the same prompt plus a sentence saying that the page holds more than
    one table and that only the table whose columns are listed is to be extracted, and an extra
    text part naming each other table on the page with its columns. The retry rule is unchanged:
    one retry with the problems named, then `ExtractionError`.
14. **Per-table layouts.** `page_layouts(columns, layers)` is called once per table with that
    table's columns and the **uncropped** layers of the pages it is on. The uncropped layer is
    used because the header sits above the first data row, outside the band. Pages without a
    header inherit the previous layout of that table, as today.
15. **Per-table grounding, position check and recheck.** For each table, `ground_document` runs
    with the table's own columns, rows and layers (the cropped layers), then `recheck_table`
    runs as today. The position check never sees rows of another table. Because the recheck sends
    `table.layers[page].lines()`, the recheck of a table on a multi-table page shows the model
    only that table's band of text. `recheck_table`, `grounding.py` and `position.py` are not
    changed.
16. **Concurrency and caps.** Extraction requests across all tables and pages still run at most
    `MAX_CONCURRENT_REQUESTS` at a time. `max_requests` counts the discovery requests like any
    other.
17. **Cache.** The discovery request changes, so cached schema answers from before this spec are
    not reused. Extract and recheck requests of a document are cached as before (their cache key
    includes the column descriptions, which now come from the inventory, so in practice they are
    re-asked too).

## Design

- `src/gridkey/models.py`: add the discovery output models (`TableInfo` with `label`, `columns`,
  `first_row`, `last_row`; a per-page entry; the window answer). `TableSchema` stays as the
  extraction-side description of a table's columns.
- `src/gridkey/discover.py` (new): the window loop, the prompts, the carry-forward text, the
  page-order matching, grouping into tables (signature = tokenized column names) and
  `ExtractionError` on unusable results. Returns, per table: label, `TableSchema`, and per page
  the first and last row text.
- `src/gridkey/regions.py` (new, or inside `discover.py`): per table and page, return the layer
  to use: the whole page, or the cropped band. Raises `ExtractionError` when a band cannot be
  isolated.
- `src/gridkey/extract.py`: `extract_tables_async` / `extract_tables` run discovery, then for
  each table the existing per-page extraction (`extract_page`, extended with the multi-table
  prompt and the "other tables" part), `page_layouts`, `ground_document`, `Table(...)`, and
  `recheck_table`. `SCHEMA_PROMPT` and `SCHEMA_PAGES` are removed. The module docstring is
  updated.
- `src/gridkey/table.py`: `Table.label`.
- `src/gridkey/__init__.py`: new exports.
- The scratch prototype used a per-page inventory (`inv_*`), a `proto.py` with these same steps,
  and a window script with carry-forward (`exp_win.py`). The code is rewritten for the repo; the
  scratch code is not copied in as is.

## Behaviour to expect

- A one-table PDF returns a list of one `Table`, with the same rows, grounding and recheck
  behaviour as before. Differences: discovery takes `ceil(pages / discovery_pages)` requests
  instead of one; discovery sees every page instead of the first five; the column descriptions
  come from the inventory.
- The Senate sample returns two tables: the 7-row summary (4 columns, page 1) and the detail
  table (7 columns, 124 rows over pages 1 to 3). With a window of 3 or more pages that is 1
  discovery request, 1 extra extract request (the summary page, 4 in all with the 3 detail
  pages) and the rechecks.
- Pages that print no header (all of `fy22_ag_house_original.pdf` after page 1 or 3) join the
  table they continue instead of becoming a table with invented columns.

## Limits

- Evidence is one document with two tables on a page, plus three single-table controls. Wrapped
  cells, a table that first appears in the middle of a long document, more than two tables on a
  page, and a window of more than 4 pages were not exercised.
- **Side-by-side tables are not supported.** Tables are separated by a vertical band only. Two
  tables that share vertical space make the bands overlap, and the run raises `ExtractionError`.
  A model that reports a first or last row whose text also occurs in the other table can pick
  the wrong band; the overlap rule catches some of these but not all.
- A document where any multi-table page cannot be isolated fails as a whole; better handling is
  a later spec.
- A table is the same table on another page only when its column names match after
  tokenizing. Names that drift beyond case and punctuation (`Requestor(s)` vs `Member`) make two
  tables. The carry-forward of known column names is the mitigation; there is no further
  merging step. The reverse also holds: two real tables with the same columns, anywhere in the
  document, are returned as one.
- Sequential windows mean discovery time grows with page count. The cost is one request per
  window.
- A total or subtotal row that sits between two tables belongs to whichever table the model
  assigns it to; this was stable on the Senate sample but is not guaranteed.
- Page-level context printed outside the tables (such as `Funding Year 2018` and the
  appropriation title above the Senate tables) is not captured. `label` is the model's short
  name, not that context.

## Alternatives considered

- **One discovery request per page, no carry-forward.** Rejected: invents columns on headerless
  pages (ag pages 2 and 4).
- **One discovery request for the whole document.** Same quality in tests, but a long PDF does
  not fit in one request. Windows with carry-forward cover any length; a window as large as the
  document is the same as this when the document is small.
- **Keep one table per document and add `extract_summary`.** Rejected by the user in favour of a
  list of tables.
- **`Table.tables` (a table holding sub-tables).** Rejected by the user: a list of `Table`
  objects reuses everything per table.
- **Crop by asking the model for coordinates.** Rejected: the model's pixel estimates are not
  reliable; locating the printed first and last row in the text layer gives exact positions.
- **Deterministic table detection from the text layer (gaps, rules).** Not tried; the inventory
  also supplies columns and the first and last row text, which the extraction needs anyway.

## Out of scope

- Side-by-side tables (stretches of the page split by x).
- Merging tables whose columns drift between pages, and parent/child context printed above
  tables.
- Changing the extraction prompt for single-table pages, the DPI, or the grounding, position
  and recheck rules.
- Writing the tables to files (CSV/CLI is still not ported).
- Running OCR in this library.

## Tests

All offline, no network. `FakeClient` and `make_pdf` are used; the recorded `.rows.json`
fixtures keep working through an updated `replay` helper that answers the discovery stage with
an inventory of one table per page.

- **API:** `extract_tables` and `extract_tables_async` exist with equal parameters; the old names
  are gone; a single-table sample returns a list of one `Table` with the rows it had before.
- **Windows:** the default is 4; `discovery_pages=0` raises `ValueError`; with `discovery_pages=2` on a four-page PDF the client sees two `schema` requests
  of two images each, in order, one after the other; the second request carries the tables found
  by the first (assert on the text part). With a window of 4, one request.
- **Page order:** a window whose answer writes absolute page numbers is matched by position; an
  answer with the wrong number of entries is retried once, then raises `ExtractionError`.
- **Grouping:** the same columns with different case or punctuation on two pages are one table;
  different columns are two; two tables come back in order of first appearance; no tables raises
  `ExtractionError`; unusable columns raise `ExtractionError`; a page with no table is fine.
- **Headerless page:** a window answer that reports the known columns for a page with no header
  gives one table over all pages (synthetic PDF).
- **Multi-table page (synthetic PDF with two stacked tables sharing words):** each table's layer
  holds only its own band's words (assert on word lists); the other table's words are absent;
  grounding does not match a value against the other table's text; the extract request for each
  table has the restriction and the "other tables" part, while a single-table page's request has
  neither; the rechecks send only their own band's text.
- **Unlocated:** a first row that is not in the text layer, a last row that is not, and two
  overlapping bands each raise `ExtractionError` whose message names the page and the table.
- **Layouts:** `page_layouts` is called per table with the uncropped layers of that table's
  pages (a table whose header is above its band still gets a `header` layout).
- **Recorded Senate fixture:** `tests/data/senate_expenditures_paddleocr`
  gets recorded answers (inventory and rows) from the manual run. Offline: two tables come back,
  with 7 and 124 rows, summary band of 34 words and detail band of 279 words on page 1, and no
  misplaced cell in the summary.
- **Existing tests:** `test_extract.py` and `test_recheck.py` are updated to the new names and
  to the discovery stage's new answer shape; all their assertions about grounding, retries, the
  recheck and `TextLayerError` still pass unchanged.
- **Live test** (`tests/live/`, opt-in): switched to `extract_tables`. Manual check, only with
  the user's explicit go-ahead: run the OCR'd Senate PDF and confirm two tables with the counts
  above; record the request count.

## Docs

- `README.md`: the example calls `extract_tables` and loops over the returned tables; the stage
  table describes discovery as an inventory of all pages in windows, with tables found so far
  carried forward; a short section lists what is not handled (side-by-side tables, merging
  drifting columns).
- `AGENTS.md`: update the project state, the file structure (`extract_tables`, `discover.py`),
  and the test count; add this spec to the history note.
- `extract.py` module docstring: replaces the schema-discovery and page-layout steps.

## Open questions

All resolved by the user.

1. `discovery_pages` defaults to 4 and is configurable per call (requirement 3).
2. When a table's part of the page cannot be isolated, raise `ExtractionError`; better handling
   is out of scope for now (requirement 12).
3. The recorded discovery answer and rows for the OCR'd Senate PDF are committed as a fixture
   next to it (Tests).
4. `records()` gets no table column (requirement 5).
