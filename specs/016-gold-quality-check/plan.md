# Implementation Plan: Gold check (hand-typed answers and a score for an extraction)

**Branch**: `spec/015-gold-quality-check` | **Date**: 2026-11-10 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/016-gold-quality-check/spec.md` (approved 2026-11-10, five clarifications)

## Summary

Add an optional gold check to the review app. A person draws a page sample from documents that have a
saved run, types the correct tables for each sampled page in a spreadsheet-style editor (a port of the
VRA gold annotation app, renamed "lock column / lock row"), and then asks for a score. The score is the
VRA scorer generalized to several tables per page: gold tables are paired with extracted tables, columns
are paired by name then by values, rows by best similarity, and every cell is compared at three levels.
The same report is available as `quotable gold-report`.

Approach:

- **Pure logic in a new subpackage `quotable/gold/`** (standard library only): the store, the sample
  draw, the scorer and the report formatting. No new dependency: the fuzzy similarity and the
  row/column assignment are small pure-Python functions (see research 4 and 5).
- **HTTP routes in `quotable/review/gold.py`**, registered in the existing server beside the browse and
  review routes. Two small changes to shared code: a per-route request-size limit and a `.gitignore`
  exception for the gold folder.
- **Browser side**: new plain ES modules in `quotable/review/static/` (no framework, no build step): the
  editor model and grid (`grid.js`, a port), the selectable text layer and copy clean-up
  (`textlayer.js`), the clock (`clock.js`), and the gold screens (`gold.js`, `goldentry.js`).
- Saved runs, the cache, prompts, cache keys and `extract_tables` are **not touched**. The gold check
  reads runs in format version 1 as they are.

## Technical Context

**Language/Version**: Python >= 3.11 (as the project); browser JavaScript as ES modules, node for tests

**Primary Dependencies**: none new. PyMuPDF (already a dependency) renders pages and reads the text
layer; `polars`/`pandas` are not used by the gold check

**Storage**: files in `.quotable/gold/` (`sample.json`, `pages.json`), written atomically; reports go to
`.quotable/reports/` on request. See [contracts/gold-files.md](contracts/gold-files.md)

**Testing**: pytest offline (no network, no key, no model): pure-logic tests, HTTP tests on a project
built by the real pipeline with fake models, CLI tests, and node tests for the browser modules (skipped
without node, as for spec 013). No live test: the feature never calls a model

**Target Platform**: macOS, Linux and Windows terminals; the browsers spec 013 targets (checked by hand
in Chrome only, as there)

**Project Type**: library with a command line and a local web app

**Performance Goals**: a score of 20 typical pages (about 12 rows, 6 columns) in under one second; a
page of 400 rows x 40 columns scores in under ten seconds (research 5)

**Constraints**: standard library only on the Python side; no network from the browser (CSP
`default-src 'self'`); the server never takes a file path from the browser; a save larger than 2 MiB is
refused

**Scale/Scope**: samples of 10 to 150 pages over 1 to 100 documents; tables up to the FR-022 limits

## Constitution Check

*GATE: passed before Phase 0 and re-checked after Phase 1 design.*

| Principle | Result |
| --- | --- |
| I. The text layer is the truth | Not touched. The gold check measures the pipeline and does not change grounding, rechecks or output. The README states that text copied from the page comes from the text layer (FR-039). |
| II. Fail closed on doubt | A gold file that cannot be read is never overwritten (the app and command say so). A score is refused until every sampled page is done. Gold for a PDF with another content hash is never applied. An unreadable `.quotable/.gitignore` is left as it is and the user is told. |
| III. Offline-testable, live tests opt-in | All tests are offline. No live test is needed: no model request is ever made (FR-002). |
| IV. One public entrypoint | Nothing is added to `quotable/__init__.py` (user decision). The saved-run format, prompts and cache keys do not change. |
| V. Generic by design | VRA's document families and requestor logic are not carried over. The scorer's text folds are generic Unicode and punctuation folds (research 6). |
| VI. Simplicity | No new dependency. Reuse: the review server, routing, page rendering, Wilson interval and visual design. Shortcuts are listed with their upgrade point (Complexity Tracking). |

Post-design re-check: unchanged. The design adds no public API, no dependency, no model call and no
change to the run format.

## Project Structure

### Documentation (this feature)

```text
specs/016-gold-quality-check/
├── plan.md              # This file
├── research.md          # Decisions and alternatives
├── data-model.md        # Entities, stored records, scoring structures
├── quickstart.md        # How to run and check the feature end to end
├── contracts/
│   ├── gold-api.md      # HTTP routes and the quotable gold-report command
│   └── gold-files.md    # The files in .quotable/gold/ and the CSV files
├── checklists/requirements.md
└── tasks.md             # Created by /speckit-tasks (not by this command)
```

### Source Code (repository root)

```text
quotable/
├── gold/                       # new; standard library only; everything here is internal
│   ├── __init__.py
│   ├── store.py                # GoldStore (pages.json), SampleStore (sample.json), validate, limits
│   ├── sample.py               # allocate, draw, documents_available (from saved runs)
│   ├── score.py                # normal, similarity, assign, pair_columns/rows/tables, score_page, evaluate
│   └── report.py               # Report -> text, JSON-able dict, pages CSV, cells CSV
├── review/
│   ├── gold.py                 # new; HTTP routes of the gold check
│   ├── routing.py              # Route gets max_body (default 64 KiB)
│   ├── server.py               # honours Route.max_body; adds GOLD_ROUTES
│   ├── sources.py              # + render of a page at 200 dpi with a turn; text-layer words of a page
│   └── static/                 # + grid.js, textlayer.js, clock.js, gold.js, goldentry.js; app.js, route.js, chrome.js, app.css extended
├── storage.py                  # + gold_dir, reports_dir, ensure_gold_trackable
└── __main__.py                 # + gold-report

tests/
├── gold/                       # new: test_store, test_sample, test_score, test_report
├── review/
│   ├── test_gold_api.py        # new: routes over HTTP
│   └── js/                     # + grid.test.mjs, textlayer.test.mjs, clock.test.mjs, gold.test.mjs
├── test_cli.py                 # + gold-report
├── test_storage.py or test_costs.py  # + ensure_gold_trackable cases (where storage tests live)
└── review_demo.py              # + a sample with a few typed pages, for `just review-demo`
README.md, AGENTS.md            # updated in the same change (FR-039, constitution workflow)
```

**Structure Decision**: a small new subpackage for the logic that the command line and the server
share, a thin routes module next to the other routes, and new flat static modules (the server serves
`static/` by name only, so no subfolders).

## Design

### Where each requirement lands

| Requirements | Where |
| --- | --- |
| FR-001 to FR-004 (optional, no model, same rules as 013, own files only) | `review/gold.py` registered in the existing server; it writes only through `gold/store.py` and `storage.ensure_gold_trackable` |
| FR-005 to FR-010 (sample) | `gold/sample.py`, `GET/POST /api/gold`, `gold.js` |
| FR-011 to FR-022 (editor, copy, lock modes, clock, rotation, saving) | `grid.js`, `textlayer.js`, `clock.js`, `goldentry.js`, `gold/store.py` (validation) |
| FR-023 to FR-035 (scoring) | `gold/score.py`, `gold/report.py`, `GET /api/gold/score`, `gold-report` |
| FR-036 to FR-038 (storage) | `gold/store.py`, `storage.py` |
| FR-039 (docs) | `README.md`, `AGENTS.md` |

### The scorer (`gold/score.py`)

Port of `scripts/analysis/gold_eval.py` with these changes (research 3 to 8):

1. A page has several gold tables and several extracted tables. `pair_tables` pairs them one to one by
   the total similarity of their paired rows, and refuses a pair under the row threshold.
2. `pair_columns` pairs by normalized name where unique on both sides, then the rest by how many
   normalized values they share (multiset overlap), left to right on a tie.
3. `normal` no longer blanks cells of only dots or dashes.
4. Row pairing first pairs rows equal after normalization, then assigns the rest by best similarity.
5. `evaluate(gold_pages, extracted)` returns a `Report` with totals, pages, per-table and per-document
   groups, every column pairing and the list of non-exact cells. Nothing in it reads a file or a run;
   the adapter from a saved run (`extracted_from_run`) is the only code that knows the run format.

### The store (`gold/store.py`)

`pages.json` is one JSON file holding every page record, rewritten whole and atomically under a lock
(like the VRA store, and friendly to git diffs because keys are sorted). An unreadable file raises a
typed error and is never replaced. `sample.json` is written the same way. `validate` enforces FR-013,
FR-015, FR-016 and FR-022 and checks that the page is in the sample and the hash is in it.

### The routes (`review/gold.py`)

See [contracts/gold-api.md](contracts/gold-api.md). Pages are reached by (SHA-256, page number), where
the SHA-256 must be one in the current sample; the PDF is found through the newest saved run of that
document whose file is still there and unchanged (`sources.usable_pdf`). Page images are rendered at
200 dpi with an optional turn; words come from the PDF's text layer, or from the run's saved words for a
page that run OCR'd (research 9).

### The browser side

`grid.js` is the VRA `grid.js` with its pure model functions unchanged (their node tests port too) and
its DOM built with the app's `el`. `goldentry.js` is the VRA `app.js` split: the page viewer with
rotation and zoom, the table tabs (one per gold table), the toolbar (Add column, New row, Lock column,
Lock row, Undo, Redo, Page done, Reset timer), the clock and the key capture of FR-020. `gold.js` holds
the sample screen (choose documents, size and seed; the page list with the progress and time-left line)
and the score screen. Hash routes: `#/gold`, `#/gold/page/<sha>/<n>`, `#/gold/score`.

### Shared code that changes

- `routing.Route` gets `max_body: int = 64 * 1024`; `server._read_body` reads the matched route's value.
  The gold page save uses 2 MiB.
- `storage.ensure_gold_trackable(project)` upgrades `.quotable/.gitignore` from exactly `*\n` to
  `*\n!.gitignore\n!gold/\n!gold/**\n` (verified with git in research 7), and writes that content when
  the file is missing. Any other content is left alone and reported.

### Build order (input to `/speckit-tasks`)

1. Store and limits. 2. Scorer core (normalize, assign, pairing) with the VRA test cases ported.
3. Report, CSV, `gold-report`. 4. Sample draw. 5. Routes and the server change. 6. Editor modules with
their node tests. 7. Entry screen, sample screen, score screen. 8. README, AGENTS.md, demo project.
The scorer and the store have no browser dependency, so steps 1 to 4 deliver a working command
(`gold-report` over hand-written gold files) before any screen exists.

### Risks and open points

- **Pairing thresholds** (50% row minimum, 90% fuzzy cutoff, 50% column overlap) are first guesses.
  They are checked on the synthetic fixture with injected faults (SC-002, SC-003) and recorded in
  research once measured.
- **Browser behavior** of the ported editor (selection, clipboard, key capture, rotation of the text
  layer) is verified by hand in Chrome with the demo project; Firefox and Safari are not checked, as in
  spec 013.
- **OCR'd pages without a table in the run** have no selectable text (research 9); the typist types them.
- **Hash collisions between two files** are not a concern; the key is a SHA-256.
- **A user who edits `pages.json` by hand** can break a record. `validate` is applied when reading, and a
  bad record is skipped with a notice naming it; the file is not rewritten until the next save.

## Complexity Tracking

| Item | Why needed | Simpler alternative rejected because |
| --- | --- | --- |
| A new subpackage `quotable/gold/` | The command line and the server both need the store and the scorer, and neither should import the other | Putting the logic in `review/` makes `gold-report` import the HTTP server's package for no reason |
| Pure-Python similarity and assignment (about 60 lines) | No new dependency (rapidfuzz, scipy and numpy are not installed; every user would pay for them) | Adding `rapidfuzz` and `scipy` is two dependencies for one optional feature (constitution VI) |
| `Route.max_body` in shared server code | A page of gold can be several hundred KiB; the global 64 KiB cap would refuse real tables | Raising the cap for every route widens the limit for endpoints that need none of it |
| `.quotable/.gitignore` upgrade | The clarified requirement: gold can be committed, the rest stays ignored (FR-036) | Leaving `*` makes the gold uncommittable; writing the exception always (even for new folders) changes spec 011/013 behavior for projects that never use the gold check |
| Exact-equal rows paired first | Keeps a 400-row page fast without scipy | Full similarity matrix for every page is slow in pure Python (research 5) |
