# 013 - Review app: browse extracted tables and review the grounding

Status: draft, features only; waiting for the user's review and answers to the open questions.
The visual design is added in a later step by a designer (see "Visual design").

## Summary

A local web app, started with `quotable review`, that lets a person look at what
`extract_tables` produced and check it against the PDF:

- **Browse.** Every run of `extract_tables` in a project, every table of a run, every row and
  cell of a table, each cell's grounding status, and the PDF page it came from with the matched
  words highlighted.
- **Review.** Walk through flagged cells (or a random sample of them), look at each one on the
  page, and record a verdict: correct, changed (with the right value and why the model was
  wrong), or can't tell. The app shows how many values are wrong with a confidence interval.

Verdicts are stored as an audit file in `.quotable/review/`. They do not change the output of
`extract_tables`, `records()` or the DataFrames (see Out of scope).

To make this possible, `extract_tables` saves each run's results to `.quotable/runs/`, the way
spec 011 saves each request's cost to `.quotable/cost/`.

```console
$ quotable review
Serving the review app at http://127.0.0.1:8765 (Ctrl+C to stop)
Runs: 12 in .quotable/runs/
```

The app is modelled on the two review apps of the original project
(`apps/grounding_review/` and `apps/unmatched_review/` in the VRA community-projects
repository). Most features below come from `grounding_review`; the row list, filters, pager
and full-PDF view come from `unmatched_review`. What is specific to VRA (matching rows to House
requests) is not carried over.

## Motivation

- Grounding says which values were found in the PDF's text, but someone still has to look at
  the flagged ones. Today that means printing `table.flagged()`, opening the PDF by hand and
  finding the page, row and column.
- The original project needed a review app to trust its numbers. Every user of quotable has the
  same need, and the library already holds everything the app shows (values, statuses, boxes,
  text layers, recheck proposals, merges, OCR pages).
- A sampled review with a confidence interval answers "how good is this extraction?" with a
  number instead of an impression.

## Terms

- **Run**: one call of `extract_tables` on one PDF. It has an id (the run id spec 011 already
  writes into every cost record), a time, a model, the settings, and the tables it returned.
- **Cell**: one value of one row of one table (a PDF column).
- **Extra field**: a value printed outside the table (spec 010). It belongs to the page that
  prints it and is copied onto every row of that page (and of later pages when carried
  forward). It is reviewed once per printing page, not once per row.
- **Flagged**: a cell or extra field whose status is not `exact`, `empty` or `not_on_page`
  (`grounding.UNFLAGGED`), as `Table.flagged()` defines it.
- **Verdict**: a reviewer's decision about one cell or extra field: `correct`, `changed` or
  `unsure`.

## Requirements

### A. Saving runs

1. **Every run is saved.** When `extract_tables` (or `extract_tables_async`) returns, it writes
   the run to `.quotable/runs/<run id>/` in the current working directory, using the same run id
   as the cost log. Like costs, the location does not depend on `cache_dir`. No new parameter
   (see open question 1).
2. **What a run holds.** Enough to show everything in sections B to D without the model, the
   cache or (except for page images) the PDF:
   - Run: format version, run id, start and end time (UTC), quotable version, model name as the
     cost log writes it, the settings that change results (`discovery_pages`, `recheck`, `ocr`,
     `merge_reworded`, `extra_fields` with their descriptions, `max_requests`).
   - Document: the PDF's file name, absolute path, size, SHA-256 and page count.
   - Each table, in the order `extract_tables` returned them: its index, `label`, `columns`,
     pages, `ocr_pages`, `position` counts, `layouts` (per page: columns and whether the header
     was found or inherited), `merged` parts with their `MergeEvidence`, `proposals` (every
     recheck proposal with its outcome), `extra_names`, `extra_fields`, `extra_changes`.
   - Each row: page, row number, values, and each cell's grounding (`status`, `coverage`,
     `density`, `n_candidates`, `matched_text`, `bbox`, and the box of every candidate).
   - Each page of each table: the text layer's words with their boxes (from OCR on an OCR'd
     page), the page size, the table's band of the page when it shares the page with another
     table (spec 004), and the areas the position check fitted: each row's vertical window and
     each column's horizontal range (requirement A5).
3. **A failed run saves nothing.** If `extract_tables` raises (`TextLayerError`,
   `BudgetExceededError`, `ExtractionError`, `OcrUnavailableError`, anything else), no run
   folder is left behind. A run is written to a temporary name and renamed into place when
   complete, so the app never sees a half-written run.
4. **Saving can never break an extraction.** If the folder cannot be written, quotable warns
   once on stderr and returns the tables as usual (as spec 011 requirement 7).
5. **The position check keeps its areas.** Today `check_positions` fits row windows and column
   ranges, uses them and throws them away. It keeps them so the run can store them. Its
   verdicts, counts and the rest of the pipeline do not change.
6. **Nothing else changes.** Cache keys, prompts, answers, `max_requests`, the cost log, the
   public API and `quotable.__all__` stay as they are. A run that is answered entirely from the
   cache is still saved (it is a run; it costs nothing).
7. **Runs pile up.** Nothing deletes old runs. Deleting `.quotable/runs/<run id>/` removes a
   run; deleting `.quotable/runs/` removes all of them and leaves the cache, costs and reviews
   alone (spec 011's one-folder-per-kind rule).

### B. Starting the app

1. **`quotable review`** is a new subcommand of the existing `quotable` command (next to
   `cost-report`; `python -m quotable review` works too). It starts a local web server, prints
   its address, and opens the default browser on it.
   - `--dir PATH`: the project's `.quotable/` folder, as for `cost-report`. Default: the one in
     the current directory.
   - `--port N`: default 8765. If the port is taken, exit 1 with a message that says so and
     suggests `--port`.
   - `--no-browser`: print the address but do not open a browser.
   - `--run ID`: open straight on this run.
   - No runs yet: the app still starts and says how to make one (run `extract_tables`).
   - Ctrl+C stops it; exit 0. A usage error exits 2 (argparse's default).
2. **Local only.** The server listens on 127.0.0.1 only, has no login, and rejects any request
   whose `Host` or `Origin` header is not `127.0.0.1:<port>` or `localhost:<port>` (this stops
   a web page in the same browser from reading or writing through it).
3. **Read-only except for reviews.** The app never changes a run, the cache, the cost log or
   the PDF. The only files it writes are in `.quotable/review/` (section F).
4. **Untrusted text is shown as text.** Values, PDF text, model answers, labels, column names
   and notes are always displayed as plain text, never interpreted as HTML.
5. **It only serves what it knows.** Files are reached by run id and page number, never by a
   path from the browser. A run id must name a folder in `.quotable/runs/`; a page number must
   be a page of that run's document.
6. **No new dependency.** The server uses the standard library; pages are rendered with
   PyMuPDF, which quotable already depends on. The browser side ships as static files inside
   the package, with no build step (see open question 5).

### C. Browsing

1. **Runs list** (the start screen). One line per run, newest first: document file name, time,
   model, number of tables, rows and cells, flagged cells by status, OCR'd pages, the run's cost
   from the cost log (sum of its records; "free" if every answer came from the cache, "unknown"
   if a price is missing), and review progress (reviewed / flagged). Filter by document name
   and by model. Runs of the same document (same SHA-256) are grouped so a re-run is easy to
   find.
2. **Run screen.** The run's details (requirement A2's run and document fields), its tables
   (label, columns, pages, rows, flagged count, merged parts, OCR pages), and a warning when the
   PDF is missing or its SHA-256 no longer matches (page images then cannot be shown; values,
   statuses and text still can).
3. **Table screen.** The table's rows as a grid, in the order of `records()`: page, row, the
   values, the extra fields. Each cell shows its value and its status. Statuses have a text
   label, not only a colour.
   - **Filters**: status (any combination, including `exact`), column, page, flagged rows only,
     rows changed by the recheck, rows on OCR'd pages, rows from a merged part, review state
     (not reviewed, correct, changed, unsure, has a note). Filters combine. A "clear filters"
     control resets them. The number of matching rows is always shown.
   - **Search**: text across all values of the row.
   - **Sort**: by page and row (default) or by any column.
   - **Paging**: 100 rows a page, with previous / next and the page number, so a table of
     thousands of rows stays fast.
   - **Summary**: counts by status for the whole table and per column, the position-check
     counts (`misplaced`, `unchecked`), and the number of accepted recheck changes.
   - **Download** the filtered rows as CSV, with the same columns as `records()`.
4. **Cell view** (opens when a cell or extra field is selected, next to the page).
   - Status, with a one-sentence plain-English explanation of what it means (see "Status
     explanations").
   - The extracted value, and the text the grounding matched (`matched_text`) when it differs.
   - Coverage, density and the number of places found.
   - The whole row, with the selected cell marked and each non-exact cell's status.
   - **Recheck history**: if the recheck proposed a value for this cell, the original and
     proposed values, the status before and after, and the outcome (`accepted`,
     `not_improved`, `same_tokens`, `blank_ignored`).
   - **OCR**: a notice when the page's text came from OCR (grounding against OCR text can pass
     OCR errors into the output).
   - **Merge**: when the row comes from a part the merge step absorbed, the part's original
     column names and the evidence (header words, x-grid difference, value shapes, cells).
   - **Extra field**: the page that prints the value (which may be an earlier page when carried
     forward), and the recheck change if any.
   - **Review**: the review controls of section D and any saved verdict.
5. **Page view.**
   - The PDF page as an image, rendered on demand from the PDF on disk; zoom in, zoom out, fit
     to width.
   - **Highlights** on the image, each switchable on and off and each with a text label:
     - the words the grounding matched (`bbox`);
     - every other place the value was found (candidates), when there is more than one;
     - the row's window and the column's range from the position check, and the cell area they
       make;
     - for `misplaced`, both the cell area and where the words were found instead;
     - the table's band, when the page holds more than one table;
     - the header line and column centres the layout step found.
   - **Text layer**: a toggle that lays the stored text layer over the image as selectable
     text, so the reviewer can copy it and see exactly what grounding searched.
   - The view scrolls to the selected cell's highlight (matched words, then cell area, then
     row window).
   - **Full PDF**: a link that opens the PDF at this page in a new browser tab, and a second
     view mode that shows the PDF in the browser's own viewer (no highlights in that mode, and
     the app says so).
   - Selecting a highlighted area on the page selects the cell it belongs to.
6. **Moving around.** Previous / next cell in the current filter, previous / next row, jump to
   page. The current run, table and cell are in the URL, so a browser reload, the back button
   and a copied link return to the same place.

### D. Reviewing

1. **The queue.** The reviewer picks which cells to review: by status (default: every flagged
   status; `exact` can be added to estimate the error rate of cells that passed), by run or
   all runs, by table, by column, and whether to include extra fields. The app shows how many
   cells match ("N flagged cells match").
2. **Sampling.** Review all of them or a random sample: sample size (number and slider),
   confidence level (80, 90, 95, 99%), a target margin of error that suggests a sample size,
   and a seed with a "new seed" button. The same seed and filters give the same sample, so a
   review can be resumed and repeated. The queue's settings are remembered between visits.
3. **Progress strip.** One small mark per cell in the queue, showing its review state
   (not reviewed, correct, changed, unsure) and the current cell; hovering shows the cell's
   run, table, page, row, column and status; clicking goes to it.
4. **Verdicts.**
   - **Correct as extracted.**
   - **Change value**: a box for the right value (blank means the cell should be empty) and a
     required reason, one of the error categories below. Saving is refused if the new value is
     the same as the extracted one or no reason is chosen.
   - **Can't tell.**
   - **Note**: free text on any cell, with or without a verdict, up to 5,000 characters.
   - A saved verdict can be replaced by a new one; the latest counts.
5. **Error categories** (why the model was wrong), each with a short description in the app:

   | Category           | Meaning                                                                                |
   | ------------------ | -------------------------------------------------------------------------------------- |
   | `misspelling`      | Letters wrong                                                                          |
   | `spacing`          | Spaces or line breaks wrong                                                            |
   | `dropped_word`     | Words of the cell left out                                                             |
   | `added_word`       | Words added that the cell does not have (often from a neighbouring cell)               |
   | `hallucination`    | A value that is not on the page at all                                                 |
   | `wrong_cell`       | The value of another row or column                                                     |
   | `wrong_number`     | Digits, sign or decimal point wrong                                                    |
   | `corrected_source` | The model fixed an error that is printed in the PDF; the PDF's text is the right value |
   | `other`            | Anything else; the note should say what                                                |

6. **Drafts.** A note and a half-typed corrected value are saved while typing (a short pause
   after the last key, and when the box loses focus) and come back when the cell is opened
   again, also after a reload. Saving a verdict clears the draft. The app shows whether the
   draft is saved.
7. **Keyboard.** Previous / next cell, next unreviewed cell, correct, change, can't tell, pick
   an error category, save, cancel. The shortcuts are listed in the app. Every action also
   works without a keyboard shortcut, and every control can be reached with the keyboard.
8. **Stale verdicts.** A verdict records the value it judged. If a later run of the same
   document has a different value in that cell, the verdict is shown as stale with both values,
   and the cell counts as not reviewed in that run (see open question 3).
9. **Extra fields** are reviewed once per printing page and field. The verdict shows on every
   row that carries that value.

### E. Statistics

Shown for the current queue and updated after each verdict:

- Population (cells matching the queue's filters) and sample size.
- Margin of error before reviewing (worst case, $p = 0.5$) and after the verdicts so far, at
  the chosen confidence level, with the finite-population correction
  $\sqrt{(N - n)/(N - 1)}$ applied and shown.
- Share of reviewed cells marked `changed`, with its Wilson score interval, and the estimated
  number of wrong cells in the population (share times population, with the interval).
  `unsure` verdicts are counted separately and left out of the share.
- A table by status: population, sampled, reviewed, changed, share changed.
- A table of error categories with counts, when any cell was changed.

### F. Storing reviews

1. **Where.** `.quotable/review/verdicts.jsonl` (one JSON object per line, appended; the latest
   line for a cell wins) and `.quotable/review/drafts.json` (replaced atomically on each save).
   `.quotable/review/` survives deleting the cache or the runs.
2. **A verdict line** holds: format version; the time (UTC); the run id; the document's
   SHA-256 and file name; the table index, label and columns; page, row and column (or the
   extra field's name and printing page); the extracted value and status at review time; the
   verdict; the corrected value and error category (for `changed`); the note; and the queue
   settings it was reviewed under (statuses, filters, seed, sample size), so the statistics can
   be rebuilt from the file.
3. **Safe writes.** Each line is written with one append (spec 011 requirement 8), so two
   browser tabs cannot interleave lines. If both save a verdict for the same cell, the later
   one wins. A write that fails is reported in the app and nothing is lost on screen.
4. **Limits.** The server refuses request bodies over a fixed size and notes or values over
   5,000 characters.
5. **Audit only.** Verdicts are not applied to anything. They are for people (and scripts)
   reading the file. The file is plain JSON Lines, readable with `polars.read_ndjson` or `jq`.

## Status explanations

Shown next to the status badge in the cell view. Draft wording:

| Status        | Explanation                                                                              |
| ------------- | ---------------------------------------------------------------------------------------- |
| `exact`       | Every word of the value is on the page, in its row and column.                           |
| `fuzzy`       | The value is on the page with small differences; compare it with the matched text.       |
| `misplaced`   | The words are on the page, but not in this cell's row and column.                        |
| `ungrounded`  | The value's words are not on the page.                                                   |
| `untokenized` | The value has no words or numbers to look up (only symbols), so it could not be checked. |
| `empty`       | The model left this cell blank.                                                          |
| `not_on_page` | This page does not print this column.                                                    |

## Visual design

Left to a designer and added to this spec in a later step. This spec fixes what the app does,
not how it looks. The designer should know:

- Two places need a lot of room at once: the page image and the cell view. The original app
  put them side by side.
- Status must be readable without colour (badges have text).
- Reviewers spend long sessions in the review screen and move with the keyboard.
- The table screen must work for tables of a few rows and of several thousand.

## Out of scope

- **Applying verdicts.** Corrected values do not flow into `records()`, the DataFrames or a
  re-run. This may come later.
- **Editing values outside a verdict**, or re-running an extraction from the app.
- **Remote or shared use**: no login, no listening on other addresses, no multi-user
  coordination beyond "the latest line wins".
- **Matching rows to an outside list** (the VRA `unmatched_review` workflow).
- **The second feature** the user has in mind for the app; a later spec.
- **Pruning old runs**, and any settings for how runs are saved.
- **Page orientation** (not ported, see README): highlights assume upright pages, as the rest
  of quotable does.

## Alternatives considered

- **Show tables passed in from Python** (`quotable.review(tables)`). Rejected (user decision):
  saving runs lets the app open any past run without the script that made it, and keeps one way
  in.
- **A Jupyter widget or a desktop app.** Rejected (user decision): a local web app works from
  any terminal and matches the original apps.
- **A web framework** (FastAPI, Flask) or a front-end build (React, Vite). Not chosen for now:
  the original apps did the same job with the standard library and plain JavaScript, and a
  dependency would be paid by every user of the library. Open question 5.
- **Store the review state in the browser** (`localStorage`). Rejected: verdicts are the audit
  record and must be in the project, next to the runs.

## Open questions

1. **Save every run, or only when asked?** Recommendation: always, as costs are, with no new
   parameter. Runs hold document content (values and the text layer), but so does the cache
   in `.quotable/cache/`, and `.quotable/.gitignore` keeps both out of git. The alternative is
   a `save_run=True` parameter to `extract_tables` (a public API change).
2. **Copy the PDF into the run?** The run stores the PDF's path and SHA-256, and page images
   are rendered from that file. If the file moves or changes, the app shows values, statuses
   and text but no images. Recommendation: do not copy. The alternative is to keep one copy per
   distinct document in `.quotable/runs/pdfs/<sha256>.pdf`, which makes runs self-contained at
   the cost of disk space.
3. **Which earlier verdicts count for a re-run?** Recommendation: a verdict applies to a cell
   in any run of the same document (same SHA-256) whose table has the same columns, at the same
   page, row and column. If the value is the same, the cell counts as reviewed; if it differs,
   the verdict is shown as stale (requirement D8). The alternative is to tie verdicts to one
   run only, which is simpler but loses the review when a document is re-run.
4. **Default port.** Recommendation: 8765, as the original app, failing with a clear message
   if it is taken. The alternative is to pick a free port automatically and print it.
5. **No front-end build step?** Recommendation: plain HTML, CSS and JavaScript files shipped in
   the package, as the original apps. The designer's work may favour a framework; if so, this
   is the time to say.
