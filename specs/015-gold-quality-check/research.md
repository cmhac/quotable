# Research: gold check

Decisions for the plan. Each has the choice, the reason and what was not chosen. Evidence that still has
to be gathered is in section 16.

## 1. Where the code lives

- **Decision**: logic in a new subpackage `quotable/gold/` (`store`, `sample`, `score`, `report`);
  routes in `quotable/review/gold.py`; command in `quotable/__main__.py`.
- **Why**: `gold-report` and the server both need the store and the scorer. The scorer has no HTTP in it
  and can be tested with plain lists. Spec 012 already splits the package by what a module does.
- **Not chosen**: everything under `review/` (the command would import the server package to score).

## 2. One JSON file for all gold pages

- **Decision**: `.quotable/gold/pages.json`, one object keyed `<sha256>:<page>`, rewritten whole and
  atomically (`storage.write_atomic`) under a lock. Keys and records are written in sorted order with
  an indent of 1.
- **Why**: the user will commit this file (clarification 3). A rewrite-whole file with stable key order
  gives small, readable diffs, and the VRA app used the same design. The editor saves every 400 ms while
  typing; appending a full-page record per save, as `verdicts.jsonl` does, would grow a committed file
  without bound.
- **Not chosen**: an append-only JSON Lines file with the latest line winning (right for verdicts,
  which are small and few; wrong for whole-page tables saved often).
- **Safety**: a file that exists but cannot be parsed raises an error and is not replaced, because the
  gold is irreplaceable (unlike drafts, which `DraftStore` renames to `.bad`). Two tabs: the later
  save of a page wins, as the spec says; the lock stops two saves from losing each other's other pages.

## 3. Pairing gold tables with extracted tables on a page

- **Decision**: build a matrix between gold tables and extracted tables on the page, where the score of a
  pair is the total similarity of its paired rows (0 when either has no rows). Assign one to one by
  best total. A pair needs at least one paired row (rows themselves pair at 0.5 or more): otherwise
  the gold table is missed and the extracted table's rows are extra.
- **Changed while implementing**: the plan divided the total by the larger row count and applied the
  0.5 threshold to that. That left a table the pipeline cut short (2 of 10 rows) unpaired, so its two
  correct rows counted as extra. The total itself lets a cut-short table pair with its gold.
- **Why**: FR-025 forbids relying on the order typed or on names. Values are what the two sides share.
  Most pages have one table on each side, where the assignment is trivial.
- **Edge decided**: a gold table with named columns and no rows has similarity 0 to everything, so it
  is unpaired and every extracted row on the page is extra (spec edge case).
- **Not chosen**: pairing by position on the page. Quotable's tables carry bands only on shared pages and
  the typist does not mark where a table sits.

## 4. The similarity function

- **Decision**: normalized Indel similarity, `2 * LCS / (len a + len b)`, which is what the VRA scorer
  got from `rapidfuzz.fuzz.ratio`. Two empty strings are identical (1.0). Equal strings return 1.0
  without any work. Written as a short dynamic-programming function with one row of memory.
- **Why**: SC-004 asks for the VRA numbers on the VRA cases. `difflib.SequenceMatcher` gives a different
  measure (it can disagree with Indel by a few points), so it would break that equivalence.
  `rapidfuzz` is not a dependency of quotable and would be paid for by every user.
- **Cost**: O(len a x len b) per differing pair. A cell is at most 2,000 characters, and most differ by
  a few characters. The cap is stated as a shortcut in the code.

## 5. Row assignment and speed

- **Decision**: two steps. First pair rows that are equal after normalization (any order; duplicates pair
  in order). Then build the similarity matrix for the remaining rows and solve the assignment problem
  with the Hungarian method, written out (about 30 lines, O(n^3)). Keep pairs at or above 0.5.
- **Why**: scipy's `linear_sum_assignment` is not available without scipy. Pairing equal rows first
  leaves only the rows that differ, which is a handful per page for a good extraction, so the matrix is
  tiny in practice and a 400-row page stays fast.
- **Is "equal first" exact?** Equal rows have similarity 1.0, the maximum, and equal rows are
  interchangeable, so pairing them first cannot lower the total or change a count. The assignment test
  compares the result with an exhaustive search on small random inputs.
- **Performance check**: a test builds a 400-row, 20-column page with 20 rows altered and requires the
  score in under ten seconds (the plan's goal; actual time recorded here once measured).

## 6. Normalization (`normal`)

Port of the VRA `normal`, with these decisions:

- **Kept**: whitespace squash, Unicode compatibility form (NFKC), curly quotes to straight, two single
  quotes to one double quote, case-folding, all dashes to a hyphen, line-break hyphen (`Expan- sion`),
  thousands commas and `$` dropped, trailing periods dropped, `;` lists order-insensitive, soft hyphens
  removed.
- **Changed (spec 014)**: the final rule that returned `""` for a cell of only dots or dashes is gone.
  A trailing-period strip that would empty the text is skipped, so `....` stays `....`. A test pins this.
- **The U+02BB fold** (modifier letter turned comma, printed as a curly quote) is kept. It is a quote-like
  character in any language, not a VRA word list (constitution V).
- **Not handled**, as in the VRA scorer: split accents (`e` plus a combining mark are folded by NFKC, but
  the PDF text layer's separate-mark accents come from the copy, not the scorer), and spaces around
  dashes or before commas.

## 7. Making only the gold folder committable

- **Decision**: `.quotable/.gitignore` containing exactly `*\n` is replaced by
  `*\n!.gitignore\n!gold/\n!gold/**\n`. A missing file gets the same content. Any other content is
  left alone and the user is told.
- **Verified** in a scratch repository: with that content `git add -A -n` lists `.quotable/.gitignore`
  and `.quotable/gold/pages.json` and nothing else under `.quotable/`.
- **Why `!.gitignore` too**: `*` also matches the `.gitignore` file, so today it is not tracked. In a
  fresh clone `.quotable/` would exist (it holds the committed gold) with no ignore file, and the next
  run's cache and runs could be committed by `git add .`. Tracking the ignore file closes that gap.
- **Not chosen**: changing the content quotable writes into every new `.quotable/`. Projects that never
  use the gold check keep today's file; spec 011 and 013 tests keep passing.

## 8. Pairing columns

- **Decision**: (1) columns whose normalized names (letters and digits, case-folded) are equal, when the
  name is unique on both sides, are paired. (2) The remaining gold and extracted columns are scored by
  multiset overlap of their non-empty normalized values, `shared / max(count a, count b)`, and assigned
  with the same Hungarian function, keeping pairs at or above 0.5 and breaking ties left to right.
  (3) The rest are unpaired.
- **Why**: FR-026 says the typist must not have to copy the model's names. Rows are not paired yet, so
  the comparison cannot be cell by cell; a bag of values is the one thing both sides have.
- **Known weakness**: two columns with the same values (for example two year columns) pair by position.
  The report lists every pairing so a wrong one is visible. The thresholds are tried on the fixture.

## 9. The words behind copy-from-page

- **Decision**: the page's words come from the PDF's text layer through PyMuPDF
  (`get_text("words")`), with the last word of each line marked from the library's block and line
  numbers, exactly as the VRA app did. For a page that the chosen run OCR'd and kept words for, the
  run's saved words are used and line ends are derived from their geometry.
- **Why**: FR-018 needs a line break marker to join a hyphen at the end of a line. The run keeps words
  only for pages with a table, and the OCR cache is keyed by settings that the run does not record in
  a form this code could rebuild reliably.
- **Consequence**: on an OCR'd page where the run found no table, there is no selectable text. The spec
  edge case was amended to say so.

## 10. Turning the page

- **Decision**: the server renders the page at 200 dpi (the VRA value, sharp enough to zoom) with an
  optional turn of 0, 90, 180 or 270 degrees, and the browser turns the text layer with the same
  transform the VRA app used. The turn is kept per page in `localStorage`.
- **Why**: keeps the image and its text layer in one coordinate system, as in the VRA app. A CSS turn of
  the image alone would leave the page's layout box wrong.
- **Cache**: rendered pages are kept in a small least-recently-used cache keyed by SHA-256, page and
  turn.

## 11. Request size

- **Decision**: add `max_body` to `routing.Route` (default 64 KiB). The page save route sets 2 MiB. The
  server reads the matched route's limit before reading the body.
- **Why**: FR-022's limits allow a page far above 64 KiB. Other routes keep the old cap.

## 12. The interval on the page share

- **Decision**: take the Wilson interval from `review.queue.wilson` at 95%, then shrink its half-width
  by `sqrt((N - s) / (N - 1))`, where N is the document's page count and s the sampled pages (0 when
  the sample is every page). Shown only for a single-document sample. The share is the correct pages
  over the counted pages.
- **Why**: the sample is a share of the document's pages, so the plain Wilson interval is too wide, and
  013 already uses this correction for its margins. Because the score is only available when the sample
  is complete (clarification 4), the scored pages are the random sample.
- **Not chosen**: an interval for several documents (strata of unequal weight would need weighting the
  spec does not ask for), and intervals on cells or rows (cells on a page are not independent).

## 13. Drawing the sample

- **Decision**: the VRA rule without families. Each document gets one page; the rest go one at a time to
  the document with the highest `sqrt(pages) / (pages so far + 1)` that still has pages left. Pages
  inside a document are drawn with `random.Random(seed)`. Documents are ordered by (file name, SHA-256)
  so the same seed gives the same sample. The default seed is a fresh random integer, shown in the app.
- **Documents offered**: one entry per SHA-256 among the saved runs; the file name, page count and PDF
  path come from the newest run of that hash.
- **Sample size**: at least the number of documents, at most the total pages; default
  `min(20, total pages)`.
- **A new draw** asks for confirmation when a sample exists; stored gold is kept (FR-009).

## 14. The command

- **Decision**: `quotable gold-report [--dir PATH] [--run ID]... [--out DIR]`. It prints the report and
  writes `gold_pages.csv` and `gold_cells.csv` to `--out` (default `<project>/reports/`). Exit codes: 0
  scored, 1 not done or unreadable or a bad `--run`, 2 usage error (argparse).
- **`--run`**: at most one run per document (two for one document is an error naming both). A document
  with no `--run` uses its newest run.
- **Why `reports/`**: the app does not store scores (clarification 2), but a command that writes
  files needs a place; a sibling of `gold/` that the project's ignore rule covers keeps reports out of
  git, while the hand-made gold is the one tracked file.

## 15. The clock and the time-left line

- **Decision**: port the VRA rules (`clock.js`, pure functions): the clock runs only while a page that is
  not done is open and the window is in front; a page finished with no stored seconds shows `--` and is
  left out of the average; time left is `(pages not done x average of timed done pages)` less what the
  open page has used, capped at the average. It saves the time on every pause.
- **Testing**: the pure functions (`clock`, `estimate`, `roughly`) get node tests with a fake time.

## 16. Evidence gathered, and what is still open

Measured on 2026-11-10 with a one-off script over the synthetic fixture (349 files, 718 pages with a
table), building the gold from each truth file and the extraction from the same rows:

| Case | Pages scored exactly as expected |
| --- | --- |
| No fault | 718 of 718 |
| Gold typed with other column names (`c0`, `c1`, ...) and the tables in the other order | 718 of 718 |
| Rows of the extraction shuffled | 718 of 718 |
| One wrong cell in the first table and one dropped row in the last (missed cells, no extra cells, paired rows and wrong rows all as injected) | 718 of 718 |

So the first-guess thresholds (row 0.5, column overlap 0.5, fuzzy 0.9) needed no change on this fixture.
The fixture's columns hold distinct values, so it does not test a table whose columns share values
(two year columns); that case is pinned by `test_two_columns_with_the_same_values_pair_left_to_right`.

A page of 400 rows by 20 columns with 20 rows altered scores in 0.3 s (limit set: 10 s).

Still open:

- A hand check in Chrome of selection, clipboard, key capture and rotation in the ported editor with
  `just review-demo` (task T049). The node tests mount the screen over a fake browser and cover the
  pure functions, saving, the red bar and moving on, not real selection or the clipboard.
- Firefox and Safari are not checked.
