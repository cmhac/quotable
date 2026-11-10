---

description: "Task list for spec 015: the gold check"
---

# Tasks: Gold check (hand-typed answers and a score for an extraction)

**Input**: Design documents from `specs/015-gold-quality-check/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/gold-api.md, contracts/gold-files.md, quickstart.md (all present)

**Tests**: Required. The constitution (III) says new logic ships with offline tests, and the feature never calls a model, so there is no live test. Write each story's tests first and watch them fail. Browser behavior that node cannot test is checked by hand (T049), in Chrome only, by the user.

**Baseline (T001, 2026-11-10)**: `just lint` and `just typecheck` pass; `just test` runs 2,704 passed in 95 s (`-n 4`).

**Organization**: by user story. US1 is the whole thin path (sample, type, score, command), so it is the MVP. The scorer's pairing logic is built in Phase 2 because every story needs it.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: can run in parallel (different files, no dependency on an unfinished task)
- **[Story]**: US1 to US7 (the spec's user stories, in order)
- Paths are from the repository root. Commit after each task or small group, on `spec/015-gold-quality-check`; do not push.

---

## Phase 1: Setup

- [x] T001 Confirm the branch is `spec/015-gold-quality-check`, run `just lint`, `just typecheck` and `just test`, and write the number of passing tests into the Baseline line of `specs/015-gold-quality-check/tasks.md`. Every later run must match it plus the new tests.
- [x] T002 [P] Create the empty packages `quotable/gold/__init__.py` (docstring: spec 015, the gold check, standard library only, internal) and `tests/gold/__init__.py`.

---

## Phase 2: Foundational (blocks every story)

**Purpose**: the store, the folders, the server size limit, the sample draw and the scorer's pure core.

- [x] T003 [P] In `quotable/storage.py` add `GOLD_DIR_NAME = "gold"`, `REPORTS_DIR_NAME = "reports"`, `gold_dir(project_dir)`, `reports_dir(project_dir)` and `ensure_gold_trackable(project_dir) -> str | None` (research 7): `.quotable/.gitignore` that is exactly `*\n` becomes `*\n!.gitignore\n!gold/\n!gold/**\n`; a missing file gets that content; any other content is left alone and the function returns a note saying the gold folder may be ignored; writes use `write_atomic`; an `OSError` returns a note and never raises. Tests in `tests/gold/test_trackable.py`: each of the three cases, the note text, and (skipped when `git` is absent) a scratch repository where `git add -A -n` lists `.quotable/.gitignore` and `.quotable/gold/pages.json` and nothing else under `.quotable/`.
- [x] T004 [P] Create `quotable/gold/store.py` per `data-model.md` and `contracts/gold-files.md`: `GoldTable`, `GoldPage`, `SampleDoc`, `Sample`, the error type `GoldError` (typed, constitution II), `validate_page(payload, sample)` and `GoldStore` / `SampleStore`. Validation quotes the data model verbatim: `columns` "1 to 40; at most 2,000 characters each; on a done page every name non-empty and distinct within the table"; `rows` "at most 400; each row has exactly one text per column; at most 2,000 characters per cell; untouched empty rows at the bottom are dropped before storing"; at most 10 tables per page; `seconds` "0 up to 7 days; null for a page finished before timing"; `sha256` and `page` must be in the current sample. A page record is replaced whole; `pages.json` is rewritten whole under a lock with sorted keys, indent 1 and a final newline, through `write_atomic`; a file that exists but is not version 1 JSON raises `GoldError` naming the file and is never replaced; a bad record is skipped with a notice. Tests in `tests/gold/test_store.py`: round trip, every limit refused with a message naming it, empty bottom rows dropped, last save of a page wins, two pages saved from two threads both survive, an unreadable file is not overwritten, the file text is stable (sorted, indent 1).
- [x] T005 [P] In `quotable/review/routing.py` add `max_body: int = 64 * 1024` to `Route`; in `quotable/review/server.py` make `_read_body` take the matched route's `max_body` (the error message states the limit). Tests in `tests/review/test_server.py`: a route with `max_body=200000` accepts a 100 KiB body, another route still refuses 70 KiB with 413.
- [x] T006 [P] Create `quotable/gold/sample.py`: `documents_available(project_dir)` (one entry per SHA-256 among `list_runs`, name, page count and PDF path from the newest run, `pdf` status from `review.sources.pdf_status`), `allocate(sizes, n)` (one page each, then one at a time to the document with the highest `sqrt(pages) / (pages so far + 1)` that has pages left, ties by name then SHA-256) and `draw(docs, n, seed)` (`random.Random(seed)`, documents ordered by name then SHA-256, pages sorted). Errors: size below the number of documents or above the total pages. Tests in `tests/gold/test_sample.py`: every document gets a page, long documents get more, no page twice, the same seed repeats the draw, a different seed differs, the VRA allocation cases (a document of one page capped at its size).
- [x] T007 Create `quotable/gold/score.py`, part 1 (the text rules): `squash`, `normal` (FR-028, research 6: the VRA folds without the dots-and-dashes rule; a trailing-period strip that would empty the text is skipped), `similarity` (research 4: Indel `2 * LCS / (len a + len b)`, equal strings 1.0 with no work, two empty strings 1.0), `score_cell` (exact, normal, fuzzy at 0.9), `column_key`, and `assign(matrix, maximize)` (Hungarian method, research 5). Tests in `tests/gold/test_score_text.py`: the VRA `normal` cases ported from the VRA repository's `tests/test_gold_eval.py` (formatting folds, name order, quotes, soft hyphen), `....` and `---` compare as they are and differ from an empty cell, `similarity` equals the known `rapidfuzz.fuzz.ratio` values for a table of 10 string pairs written into the test as literals, and `assign` equals an exhaustive search on 200 random small matrices.
- [x] T008 Same file, part 2 (the pairing): `pair_columns` (name first when unique on both sides, then multiset overlap `shared / max(count a, count b)` of normalized non-empty values, assigned with `assign`, pairs under 0.5 dropped, ties left to right; returns the pairs and, for each, `how` of `name` or `values`), `pair_rows` (rows equal after normalization first, the rest by mean cell similarity over columns where either side has text, assigned, pairs under `ROW_MATCH = 0.5` dropped), `pair_tables` (research 3: similarity of a pair is the sum of its paired-row similarities over the larger row count; a gold table with no rows has similarity 0; assigned; under 0.5 unpaired), `Counts` (data model) and `score_page(sha, page, gold_tables, extracted_tables)` returning a `PageScore` with `pairs`, `unmatched_gold`, `unmatched_extracted`, `details`, `counted` and `correct` as the data model defines them. Tests in `tests/gold/test_score_pairs.py`: the VRA `score_page` cases ported (unpaired rows and columns missed or extra, row and page accuracy at the normal level), column names that differ pair by values and the pairing is reported, two columns with the same values pair left to right, equal-rows-first gives the same counts as a full assignment on 200 random small pages, and a page of 400 rows by 20 columns with 20 rows altered scores in under ten seconds.
- [x] T009 Same file, part 3 (the adapter): `ExtractedTable` (data model) and `extracted_from_run(run)` that builds one per `RunTable` from `run.tables[*].rows` (columns in the table's order, missing values `""`, rows sorted by row number per page). Tests in `tests/gold/test_score_pairs.py`: a `Run` built from dataclasses gives the expected tables, a table with rows on two pages, a missing column value.

**Checkpoint**: `just test tests/gold tests/review/test_server.py` passes; `just lint` and `just typecheck` pass. The scorer can already score lists in memory.

---

## Phase 3: User Story 1 - Check one document with a sample of pages (P1) 🎯 MVP

**Goal**: a user with a saved run of one document draws a sample, types gold, and reads a score in the app or with `quotable gold-report`.

**Independent Test**: with the synthetic fixture and fake models (`tests/review/test_browse_api.py`'s project), draw a sample over HTTP, save gold built from the fixture's truth file with injected faults, and read the score: the counts equal the injected faults (SC-002); every figure is 100% without faults.

### Tests for User Story 1 (write first, watch them fail)

- [x] T010 [P] [US1] `tests/gold/test_evaluate.py`: `evaluate` over in-memory gold and extracted tables returns the headline `units` (cell, row, page: correct, gold, extracted, in either, recall, precision, accuracy at the normal level), the three-level cell accuracy, paired/missed/extra rows and cells, a page with no table on either side is not counted, and the SC-002 fault test: gold from a fixture truth file, extraction with 3 wrong cells, 1 dropped row and 1 extra row, reported counts equal exactly. A one-document sample gives the interval with the finite-population shrink (equal to `queue.wilson` when every page is sampled shrunk to zero width, wider than the plain Wilson never).
- [x] T011 [P] [US1] `tests/gold/test_report.py`: `format_text` prints the headline table, the definitions of cell, row and page, the run used for each document and the interval line; "N of M pages are done" and no figures for an incomplete sample (FR-023); `pages_csv` and `cells_csv` have the columns of `contracts/gold-files.md` and prefix a cell that starts with `=`, `+`, `-` or `@` with `'`.
- [x] T012 [P] [US1] `tests/review/test_gold_api.py` (uses the `built` and `app` fixtures of `tests/review/test_browse_api.py`): `GET /api/gold` before a sample (documents offered, `sample` null), `POST /api/gold/sample` (seeded and repeatable, 400 for an empty list, an unknown document, a size out of range, and an existing sample without `replace`), `GET`/`PUT /api/gold/pages/<sha>/<n>` (record round trip, every FR-022 limit is a 400, a done page with an unnamed column is a 400, a body over 2 MiB is 413), `.../words` (words with a `line_end` flag), `.../<n>.png` with `rot` 0/90/180/270 and a 400 for another value, a page of a document not in the sample is 404, `GET /api/gold/score` incomplete lists what is left and complete returns the report, and `.quotable/.gitignore` is upgraded on the first draw. The app never sends or accepts a file path.
- [x] T013 [P] [US1] `tests/test_cli.py`: `gold-report` prints the report and writes `gold_pages.csv` and `gold_cells.csv` to `<project>/reports/`; exit 1 with no sample, with a message "N of M pages are done" for an incomplete sample, and for an unreadable `pages.json`; exit 2 for a usage error; the gold check never touches `.quotable/runs/`, `.quotable/cache/`, `.quotable/cost/` or `.quotable/review/` (byte-for-byte snapshot, SC-007), and the cost log has no new line.
- [x] T014 [P] [US1] `tests/review/js/grid.test.mjs`: the VRA `tests/gold_grid.test.mjs` cases ported to the new `grid.js` (cell value, set, clear, paste with added columns, fill, `parseTsv`, `toTsv`).

### Implementation for User Story 1

- [x] T015 [US1] `quotable/gold/score.py`, part 4: `evaluate(sample, gold_pages, extracted_by_doc)` returning the `Report` of the data model (`units`, `total`, `per_document`, `interval`, `cells`, `not_scored`, `runs`; `per_table` and column pairings are completed in T027), the interval of research 12 for a single-document sample, and `progress(sample, gold_pages)` returning done, total and what is left.
- [x] T016 [US1] Create `quotable/gold/report.py`: `format_text(report)` (the VRA layout: counts, definitions, rows, cell levels), `to_json(report)` and `pages_csv` / `cells_csv` (standard `csv`, the formula prefix of the contract).
- [x] T017 [US1] In `quotable/__main__.py` add `gold-report` with `--dir` and `--out` (`--run` is added in T044): load the sample and gold, refuse an incomplete sample (exit 1 with the count), score each document against its newest run (the PDF need not be present), print, write the two CSV files, and update the module docstring's exit-code paragraph.
- [x] T018 [US1] In `quotable/review/sources.py` add `render_gold_page(summary, page, rot)` (PyMuPDF at 200 dpi with `Matrix.prerotate(rot)`, a small LRU keyed by SHA-256, page and turn, `NotFound` with the reason for a missing or changed PDF, reusing `usable_pdf`), `text_words(summary, page)` (research 9: the text layer's words with `line_end` from block and line numbers; for a page the run OCR'd and kept words for, those words with line ends derived from geometry by a pure `line_ends(words)`) and `newest_run_for(project_dir, sha)`. Tests for `line_ends` and the OCR choice go in `tests/review/test_gold_api.py`.
- [x] T019 [US1] Create `quotable/review/gold.py` with `ROUTES` for `GET /api/gold`, `POST /api/gold/sample`, `GET`/`PUT /api/gold/pages/<sha>/<n>`, `.../words`, `.../<n>.png` and `GET /api/gold/score` (contracts/gold-api.md; the PUT route has `max_body` of 2 MiB; a `GoldError` becomes `ServerError`; `ensure_gold_trackable` runs on draw and the note is returned as `tracked`) and add `GOLD_ROUTES` to `API_ROUTES` in `quotable/review/server.py`. Update the docstring of `server.py` and the route list there.
- [x] T020 [US1] Create `quotable/review/static/grid.js`: a port of the VRA `apps/gold_annotation/static/grid.js` with the model functions unchanged, DOM built with `el` from `dom.js` (SVG excepted), undo/redo, selection, editing, copy/cut/paste, fill handle, row numbers, delete of rows and columns with the confirm, and every key of FR-017. Leave the lock-mode functions out (T033).
- [x] T021 [US1] Create `quotable/review/static/goldentry.js`: the entry screen `show(route, ctx)` for `#/gold/page/<sha>/<n>` with the page image next to the editor, zoom buttons and fit, "Page done" with the FR-015 refusal shown, 20 empty starting rows and one unnamed column (FR-014), autosave 400 ms after a change, the loud red bar and retry every 3 s when the server is unreachable, refusal to leave an unsaved page, `beforeunload` guard, a 5 s heartbeat, and after "done" the next page that is not done. Nothing from the extraction is requested or shown (FR-014).
- [x] T022 [US1] Create `quotable/review/static/gold.js` with the sample screen (`#/gold`): documents offered (only those with `pdf` ok), choose one or more, size (default `min(20, total pages)`), seed shown and editable, draw with the confirm when a sample exists, the `tracked` note when present, the page list with status and "N of M pages done", and the score screen (`#/gold/score`): the incomplete message with what is left, or the headline table with definitions, runs used and the interval line. Pure view builders are exported for tests.
- [x] T023 [US1] Wire the screens: `quotable/review/static/route.js` (`gold`, `goldpage`, `goldscore` with their query), `app.js` (`SCREENS`), `chrome.js` (a "Gold check" link in the header), and `app.css` (editor, grid, page list, score table, the red bar; use the existing colours and spacing). In `tests/review/test_static.py` extend `test_app_registers_the_screens_built_so_far` with the new routes.
- [x] T024 [US1] `tests/review/js/gold.test.mjs`: the sample screen and score screen views over the fake DOM of `tests/review/js/fake_dom.mjs` (documents listed, draw button, incomplete message, headline rows, interval line, nothing inserted as markup).

**Checkpoint**: US1 works alone. Run quickstart section 2 on a project built by the test fixtures; `just test` passes.

---

## Phase 4: User Story 2 - Pages with several tables, no table, or a table that continues (P1)

**Goal**: the score and the editor handle two tables on a page, a page with none, a table the pipeline missed, and a table that continues.

**Independent Test**: on the fixture's shared-page document (`struct-shared-page`), gold typed in either order and with other column names scores the same as gold in the model's order and names.

### Tests for User Story 2

- [x] T025 [P] [US2] `tests/gold/test_score_tables.py`: the six acceptance scenarios of the spec as scores on in-memory pages (two tables paired by values in either order; a done page with no table while the extraction has rows is extra and wrong; a table the pipeline never found is all missed; renamed columns; a sample holding only pages 5 and 8 of a long table; two printed tables merged into one extracted table leave the second as missed), a gold table with named columns and no rows is unpaired and every extracted row is extra, and the SC-003 test on `struct-shared-page` (all four combinations of order and names give identical scores).
- [x] T026 [P] [US2] Extend `tests/review/js/gold.test.mjs` with the table-tab functions: adding and removing a gold table on a page, a page with zero tables can be marked done, validation names the table that has an unnamed or repeated column.

### Implementation for User Story 2

- [x] T027 [US2] Complete `quotable/gold/score.py` and `report.py`: `per_table` (by extracted table, plus a "no extracted match" line per document for unmatched gold tables), the column pairing of every page-table in the report (`how`, unpaired gold and extracted columns), and the text lines for both (FR-026, FR-031). Update `tests/gold/test_report.py` to cover them.
- [x] T028 [US2] In `quotable/review/static/goldentry.js` add the table tabs: add and remove gold tables on a page, one editor per table, "no table on this page" shown when the list is empty, and "done" with no table. Pure helpers go in `quotable/review/static/gold.js` or `grid.js` as the tests of T026 require.
- [x] T029 [US2] In `quotable/review/static/gold.js` show the per-document lines, the per-table lines, the gold tables without a partner, and the column pairing of each page-table on the score screen.

**Checkpoint**: US1 and US2 pass together; the SC-003 test is green.

---

## Phase 5: User Story 3 - Type quickly from the page (P2)

**Goal**: selecting text on the page copies it clean; lock column and lock row move through the table; every VRA shortcut works; every key goes to the table.

**Independent Test**: node tests of the pure functions, plus the manual run of quickstart section 4, steps 3 and 4.

### Tests for User Story 3

- [x] T030 [P] [US3] `tests/review/js/textlayer.test.mjs`: `cleanText` cases from scenario 1 (newlines, tabs and repeated spaces to one space; a hyphen that ends a line dropped and halves joined; a hyphen inside a line kept, for example `Cherfilus-McCormick`; leading and trailing spaces trimmed; trailing periods and spaced dot leaders removed, `Corp.` to `Corp`), `sameRange` guard so a click inside the highlight does not copy twice, and the notice text.
- [x] T031 [P] [US3] Extend `tests/review/js/grid.test.mjs` with the lock-mode functions of T033: lock column moves down and goes to the top of the next column at the end of the tallest other column, never fills the name row; lock row moves right and wraps, fills names, adds a column on the last name; Shift adds after a "."; each paste is one undo step and undo returns to its cell.

### Implementation for User Story 3

- [x] T032 [US3] Create `quotable/review/static/textlayer.js`: `renderTextLayer(svg, img, ...)` (invisible selectable SVG text from `/words`, each word stretched to its printed width and turned with the page's rotation as the VRA app does), `cleanText`, copy on mouse release (`navigator.clipboard.writeText`, the highlight stays until the next click, same-selection guard, Shift on release for "add"), and the notice (`toast`) that floats over the right end of the viewer toolbar with pointer events off, never over the page and never changing the layout height.
- [x] T033 [US3] In `quotable/review/static/grid.js` add `setLock(mode)` and `pasteNext(text, append)` with the behavior of FR-019 (the VRA `setFast` and `pasteNext`, renamed), the "lock" class on the table and the tint while Shift is held.
- [x] T034 [US3] In `quotable/review/static/goldentry.js` add the "Lock column" and "Lock row" buttons (one on at a time, clicking the lit one turns it off; titles and messages say "lock", never "fast"), the whole-PDF view (every page stacked, images and text layers loaded as they scroll near, the sampled page marked), hiding the page list, pinch zoom, and the document-level key capture of FR-020 (every key to the table wherever focus was last clicked, arrows and ⌘ combinations included, browser shortcuts such as ⌘L, ⌘T, ⌘W, ⌘[ and F5 left alone, Home, End, Page Up and Page Down swallowed, a text box being typed in keeps its keys, the clipboard shortcuts through the table's hidden text box with the page highlight restored).
- [x] T035 [US3] Add the styles for the text layer, the notice, the lock modes and the Shift tint to `quotable/review/static/app.css`.

**Checkpoint**: node tests pass; the manual steps 3 and 4 of the quickstart are listed for the user (T049).

---

## Phase 6: User Story 4 - Know how long it takes and turn the page (P2)

**Goal**: a per-page clock, a time-left line, and a page that can be turned.

**Independent Test**: node tests with a fake clock; the rotation transform test; quickstart step 5.

### Tests for User Story 4

- [x] T036 [P] [US4] `tests/review/js/clock.test.mjs`: the clock runs only while a page that is not done is open and the window is in front, pauses and keeps the time, stops on done, resumes when reopened, reset to 0; a page finished with null seconds shows `--` and is left out of the average; the time-left line `N of M pages done · about X left · Y a page on average (K timed)` with X the pages not done times the average, less the open page's time capped at the average; before any timed page the line says the estimate appears after the first one; `clock(s)` and `roughly(s)` formats.
- [x] T037 [P] [US4] In `tests/review/js/textlayer.test.mjs` test the text layer transform for 0, 90, 180 and 270 against the VRA values (`translate(h 0)`, `translate(w h)`, `translate(0 w)` with `rotate`), and that a turn is stored and read per page from a fake `localStorage`.

### Implementation for User Story 4

- [x] T038 [US4] Create `quotable/review/static/clock.js` (pure: `Clock`, `estimate`, `roughly`, `clock`) and use it in `goldentry.js`: start on first open of a page that is not done, pause on hidden tab or lost focus and save the seconds then, stop on done and store `seconds`, resume on reopening, the "Reset timer" button with the confirm, the clock shown in the toolbar, the progress bar and time-left line updated every second (FR-020a, FR-020b).
- [x] T039 [US4] Add the rotate-left and rotate-right buttons to `goldentry.js` for the page image and the whole-PDF view: the image is requested with `rot`, the text layer is turned with it by `textlayer.js`, the turn is kept per page in `localStorage`.

**Checkpoint**: clock and rotation tests pass.

---

## Phase 7: User Story 5 - See exactly where the extraction differs (P2)

**Goal**: the list of non-exact cells, with links to the page, and the same as CSV.

**Independent Test**: a score with known differences lists exactly those cells; the CSV rows match.

### Tests for User Story 5

- [x] T040 [P] [US5] In `tests/gold/test_report.py` and `tests/review/test_gold_api.py`: each non-exact cell appears once with table, page, row, column, gold, extracted and best level; a case, spacing, dash or thousands-comma difference is listed at `normal` and is not an error in the headline; `GET /api/gold/score.csv?kind=pages|cells` returns the CSV with `text/csv` and the same lines as `gold-report`; an unknown `kind` is 400.

### Implementation for User Story 5

- [x] T041 [US5] Add the `GET /api/gold/score.csv` route to `quotable/review/gold.py`.
- [x] T042 [US5] In `quotable/review/static/gold.js` add the differences list to the score screen (filter by match level, page link to `#/gold/page/<sha>/<n>`) and the two download links.

**Checkpoint**: scenario 3 of US5 holds: the command and the app agree.

---

## Phase 8: User Story 6 - Score another run against the same gold (P2)

**Goal**: choose which run is scored for a document, and refuse a changed PDF's gold.

**Independent Test**: two saved runs of one fixture document, one with injected faults, give two different scores from one set of gold.

### Tests for User Story 6

- [x] T043 [P] [US6] In `tests/gold/test_evaluate.py`, `tests/review/test_gold_api.py` and `tests/test_cli.py`: the newest run is the default; `run=` and `--run` choose another; two runs of one document is a 400 / exit 1 naming both; an unknown run id is a 400 / exit 1; a run whose document has another SHA-256 gets "no gold" and is left out with a line at the top of the report; nothing is stored between two scores.

### Implementation for User Story 6

- [x] T044 [US6] Add `--run ID` (repeatable) to `gold-report` in `quotable/__main__.py` and the `run` query handling to `GET /api/gold/score` and `score.csv` in `quotable/review/gold.py`; share one `choose_runs(project_dir, run_ids)` helper in `quotable/gold/sample.py` or `score.py`.
- [x] T045 [US6] In `quotable/review/static/gold.js` add a run selector per document on the score screen (default newest), listing each run's id start, model and time.

**Checkpoint**: scenarios 1 and 2 of US6 pass.

---

## Phase 9: User Story 7 - Several documents in one sample (P3)

**Goal**: pooled figures with a line per document and per table; no interval.

**Independent Test**: a sample of 10 pages over three fixture documents: every document has a page, longer ones more, the same seed repeats, and the report has pooled counts and one line per document without an interval.

### Tests for User Story 7

- [x] T046 [P] [US7] In `tests/gold/test_evaluate.py` and `tests/review/test_gold_api.py`: a three-document sample draws as scenario 1 requires; the pooled `total` equals the sum of `per_document`; `interval` is null; a document with no usable run is listed as not scored and left out of the totals.

### Implementation for User Story 7

- [x] T047 [US7] Check that the sample screen (`gold.js`) offers several documents and that the score screen shows the per-document lines and no interval for several; fix what the test shows. (The logic is in T015, T027 and T006; this task is the screen and any gap the tests find.)

**Checkpoint**: all seven stories pass.

---

## Phase 10: Polish and cross-cutting

- [x] T048 [P] README: add a "Gold check" section (the workflow, the three steps, blind entry, copy-from-page and the lock modes, that text copied from the page comes from the PDF's text layer so a text-layer error can be copied into the gold, that the gold folder is not git-ignored and holds text copied from the PDF so its licence matters before it is committed publicly, the command `quotable gold-report` and its exit codes, and that it never calls a model).
- [ ] T049 Hand check by the user in Chrome with `just review-demo` (the agent cannot start servers): quickstart section 4, steps 1 to 7, plus a look at the editor's keys against the VRA app. Record in this file which steps passed and what is not checked (Firefox, Safari).
- [x] T050 [P] Extend `tests/review_demo.py` so the demo project has a drawn sample and a few typed pages (one with two tables, one with no table, one with a deliberate difference), and `tests/review/test_review_demo.py` to check them; the demo must still build in about 10 s.
- [x] T051 Measure the pairing thresholds (row 0.5, column 0.5, fuzzy 0.9) on the synthetic fixture with injected faults (SC-002, SC-003) and the 400-row timing; record the numbers in `specs/015-gold-quality-check/research.md` section 16 and change a threshold only if the numbers say so.
- [x] T052 Update `AGENTS.md` in the same change: the project-state paragraph (spec 015), the file structure (`quotable/gold/`, `review/gold.py`, the new static modules, `tests/gold/`), the commands (`quotable gold-report`, not a `just` recipe, like `cost-report`) and the Spec Kit numbering note.
- [x] T053 Run `just lint`, `just typecheck`, `just hooks` and `just test`; the count must be the T001 baseline plus the new tests. Run the quickstart sections 1 to 3. Check the README, `quotable/__main__.py` docstring and `quotable/review/server.py` docstring against what was built.
- [ ] T054 `speckit-converge` is run by the user after this list is done, repeated until it reports Converged (AGENTS.md workflow).

---

## Dependencies & execution order

- **Phase 1 then Phase 2**: T003 to T006 are independent of each other; T007 then T008 then T009 (same file, in order).
- **US1** needs Phase 2. Its tests T010 to T014 come first. T015 then T016; T017 needs T015, T016; T018 then T019 (needs T003 to T006, T015); T020 then T021 and T022 (T021 and T022 touch different files and can be parallel after T020); T023 after T021, T022; T024 after T022.
- **US2** needs US1's score and screens. T027 before T029; T028 after T021.
- **US3** needs US1's editor (T020, T021). T032 and T033 are parallel; T034 needs both.
- **US4** needs T021 and T032 (the text layer turn). T038 and T039 touch `goldentry.js` and follow each other.
- **US5** needs T015 and T016. **US6** needs T017 and T019. **US7** needs T006, T015, T027.
- **Polish** after the stories wanted. T049 is the user's. T050 can start once US1 is done.

### Parallel opportunities

- Phase 2: T003, T004, T005, T006 together.
- US1 tests: T010 to T014 together. After T020: T021 and T022.
- US3: T030 and T031 together, then T032 and T033 together.
- US4: T036 and T037 together.
- Polish: T048 and T050 together.

## Implementation strategy

- **MVP**: Phase 1, Phase 2, US1. After T017 the command already scores hand-written gold files with no screen at all, which is a useful stopping point to check the numbers against the VRA scorer (SC-004) before the editor is built.
- **Order**: US1, US2 (both P1), then US3 and US4 (typing speed and the clock), US5, US6, US7, polish.
- **Not done by tasks**: the browser check (T049) needs the user; Firefox and Safari are not in scope, as in spec 013.

## Notes

- The shell hook blocks the agent from starting a server; every browser step is for the user to run.
- Do not add a dependency (constitution VI). The similarity and the assignment are written in the repository (research 4 and 5).
- Do not change the saved-run format, the cache keys, the prompts or `quotable/__init__.py`.
- FR-020a and FR-020b keep their letters in the spec; do not renumber them while building.

## Notes from building (2026-11-10)

- **Test count**: `just test` runs 2,916 passed after the convergence tasks (baseline 2,704). `just lint`, `just typecheck` and `ruff format --check` pass. `pre-commit run --files` skipped the ruff hooks for the new untracked files, so ruff was run directly on the whole repository; stage the files and run `just hooks` before committing.
- **Where tests landed**: the CLI tests are in `tests/gold/test_gold_cli.py` (not `tests/test_cli.py`); the editor smoke test is `tests/review/js/goldentry.test.mjs`, the model tests `goldmodel.test.mjs`, the view tests `gold.test.mjs`. `tests/review/js/fake_dom.mjs` gained `installBrowser()` and a few element methods.
- **Changed from the plan** (recorded in research 3): a gold table pairs with an extracted table when at least one row pairs, scored by the total similarity of its paired rows, so a table cut short still pairs. `Report` has `notes`; the score answer has `choices` (runs per document); differing cells carry `sha256`; `GET /api/gold/pages/<sha>/<n>` has no `size`; the image and words routes take any page of a sampled document (for the whole-PDF view).
- **One thing to look at**: `textlayer.js` builds the SVG namespace as `` `http:${"//"}www.w3.org/2000/svg` `` because `tests/review/test_static.py` forbids the text `http://` in any static file. It is an identifier the DOM needs, never fetched.
- **T049 is yours**: the shell hook stops the agent from starting `quotable review`, so no browser check was done. Run `just review-demo` and go through quickstart section 4 in Chrome (selection, clipboard, key capture, rotation, the red bar). Firefox and Safari are not checked. The demo project already has a finished sample, so `#/gold/score` shows a report at once; draw a new sample to test typing.
- **T054 is yours**: `speckit-converge`.

---

## Phase 11: Convergence

Found by `speckit-converge` on 2026-11-10, after `speckit-implement`. T049 and T054 above are still open and are not repeated here.

- [x] T055 CRITICAL: add `shortcut: <the limit>, <when to upgrade>` comments (one line each) where the build took a known shortcut, per Constitution VI (partial): in `quotable/review/static/goldentry.js` (`switchTable`, `onAddTable`, `onRemoveTable`: the undo history is dropped when the table on screen changes, upgrade when typists ask to undo across tables); in `quotable/review/sources.py` (`line_ends`: a geometry guess for OCR words that have no line numbers, upgrade if copied OCR text joins wrong; `newest_run_for`: reads every run's `run.json` per call, until T058); in `quotable/gold/score.py` (`pair_columns`: a bag-of-values overlap, so two columns with the same values pair by position, upgrade if the column pairing list shows wrong pairs).
- [x] T056 Make `quotable gold-report` tell the user when the gold folder may be ignored by git, per FR-036 (partial): in `quotable/__main__.py` `_gold_report`, call `quotable.storage.gold_ignore_note(project)` and, if it returns a note, print it to stderr as `quotable: <note>` after the report (exit code stays 0). Test in `tests/gold/test_gold_cli.py`: a project whose `.quotable/.gitignore` is `*.pdf` prints the note; one upgraded by `ensure_gold_trackable` and one with no `.gitignore` print nothing.
- [x] T057 Refuse to mark a page done when its PDF is missing or changed, per the edge case "A sampled page's PDF is missing or has changed" (partial): in `quotable/review/gold.py` `save_page`, when `done` is true and `sources.pdf_status` of `newest_run_for(...)` is not `ok` (or there is no run), raise `BadRequest("the PDF is missing or has changed, so this page cannot be marked done")`; in `quotable/review/static/goldentry.js` disable the "Page done" box with that reason as its title when `state.pdf !== "ok"`. Tests in `tests/review/test_gold_api.py` (done is a 400, saving without done still works, the stored record is kept) and `tests/review/js/goldentry.test.mjs` (the box is disabled for a missing PDF).
- [x] T058 Add one end-to-end test of the path in SC-001 over HTTP, per SC-001 (partial), in `tests/review/test_gold_api.py`: draw a sample of the simple document, `PUT` every sampled page with tables built from the run's own rows (`tests.gold_project.gold_from_run`), `GET /api/gold/score` and assert every unit is 100%, the interval is a point, and the cells list is empty; then change one cell in one `PUT` and assert exactly one difference is listed.
- [x] T059 Read the run list once per request, per the plan's route design (partial): in `quotable/review/gold.py` `_documents` call `list_runs` once and choose the newest usable run per SHA-256 from that list; in `quotable/review/sources.py` make `newest_run_for` use a small cache of `list_runs` keyed by the modification time and size of `.quotable/runs/` (cleared by `clear_caches`). Tests: the answers do not change (`tests/review/test_gold_api.py` passes), and a new run saved after a first call is seen by the next one.
- [x] T060 Bring `AGENTS.md` up to date with what was built, per FR-039 and the constitution's workflow rule (partial): list `tests/review/test_gold_api.py` and the node tests (`grid`, `goldmodel`, `gold`, `goldentry`, `textlayer`, `clock`) in the file structure, say that `routing.py` has `Route.max_body`, and say that `tests/review_demo.py` builds a finished gold sample.
