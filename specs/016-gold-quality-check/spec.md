# Feature Specification: Gold check (hand-typed answers and a score for an extraction)

**Feature Branch**: `spec/015-gold-quality-check`

**Created**: 2026-11-10

**Status**: Approved by the user on 2026-11-10; planned (plan.md); waiting for the task list

**Input**: User description: "Look at the old VRA analysis, specifically the gold annotation app and gold eval process. Adapt that into quotable. It should work in single and multi-table cases. It should be an optional thing the user can do if they want additional assurance of the quality of the extractions."

## Summary

Grounding and the recheck tell a user whether each extracted value is in the PDF's text layer, and the
review app (spec 013) lets a person give a verdict on the cells quotable produced. Neither can see
what the pipeline never produced: a row it dropped, a table it did not find. Neither gives a plain
figure such as "98.7% of cells are correct and 36 of 40 pages have no error".

The VRA project answered this with a **gold set**: a random sample of pages, the correct table of each
page typed by a person who reads the page image, and a script that scores the extraction against
those tables. That is the strongest check the project had, and it found problems the other checks
could not. This spec brings it over as an **optional** step with three parts:

1. **Draw a sample** of pages from one or more documents that have a saved run.
2. **Type the gold tables** for the sampled pages in a spreadsheet-style editor next to the page,
   inside the existing review app.
3. **Score** a run against the gold: recall, precision and accuracy for cells, rows and pages, a
   breakdown per table, and a list of every cell that differs.

It must work for a document with one table, for pages that hold several tables, for pages with no
table, and for a table that continues over several pages.

Nothing about `extract_tables` changes. A user who never opens the gold check sees no difference, and
the gold check never calls a model, so it costs no money.

### How it differs from the review app (spec 013)

| | Review verdicts (013) | Gold check (this spec) |
| --- | --- | --- |
| Question answered | Is this extracted value right? | What does the page really say? |
| Starting point | The extraction's cells | An empty table and the page image |
| Can find a dropped row or a missed table | No | Yes |
| Result | Error rate among reviewed cells, with an interval | Recall, precision and accuracy against a hand-made answer |
| Effort | A glance per cell | Typing every row of each sampled page |

They are complementary. The gold check reuses the review app's server, page viewer, sampling idea
and visual design; it does not replace verdicts.

## Clarifications

### Session 2026-11-10

- Q: Where does the gold check live: inside `quotable review` or as its own command? A: Inside the review app, as a "Gold check" area. It needs the same server, page images and text overlay, and one local app is simpler to start and explain. [Assumed; reverse if a separate command is wanted.]
- Q: Is the gold tied to a run or to a document? A: To the document (its content hash) and page. A re-run, or a run with another model, is scored against the same gold with no retyping. A changed PDF has no gold. [Assumed.]
- Q: Which pages can be sampled? A: Every page of the chosen documents, not only the pages where the extraction found a table. Otherwise a table the pipeline missed could never be found. [Assumed; same as the VRA draw.]
- Q: Are cells made only of dots or dashes treated as blank when scoring, as the VRA scorer did? A: No. They are compared as they are, because spec 014 stopped blanking them: quotable extracts cell contents exactly. [Assumed from spec 014.]
- Q: Is the per-page timer and time-left estimate carried over from the VRA app? A: Yes (user decision, 2026-11-10).
- Q: Is page rotation carried over? A: Yes (user decision, 2026-11-10).
- Q: Should the editor start empty, or pre-filled with the extraction? A: Blind, exactly like the VRA annotation app: it starts empty and never shows the extraction (user decision, 2026-11-10). The score is independent of the model, and dropped rows show up. A pre-filled mode is out of scope.
- Q: Should scoring be a public Python function? A: No. The score is read in the review app and with a command only (user decision, 2026-11-10). The command's CSV files read in one line with `polars` or `pandas`.
- Q: Which keyboard shortcuts does the editor keep? A: All of the VRA annotation app's (user decision, 2026-11-10); FR-017 lists them.
- Q: What are the fast column and fast row modes called? A: "Lock column" and "Lock row" (user decision, 2026-11-10). They behave exactly as the VRA app's fast modes.
- Q: Which match level decides whether a cell is correct in the headline recall, precision and accuracy? → A: Normal (user decision, 2026-11-10). Exact and fuzzy cell accuracy are reported beside it (FR-030).
- Q: Is the gold ignored by git like the rest of `.quotable/`? → A: No. The gold folder is left out of the ignore rule so the user can commit it (user decision, 2026-11-10). This changes spec 013's statement that `.quotable/.gitignore` keeps everything out of git, for the gold folder only (FR-036).
- Q: Can a document enter the gold check other than through a saved run? → A: No. A sample is drawn only from documents that have a saved run, in the app (user decision, 2026-11-10). The server never takes a file path from the browser. Drawing from PDF paths before any run exists is out of scope.
- Q: Is a score shown while only some sampled pages are done? → A: No. Scoring is unavailable until every page of the sample is done (user decision, 2026-11-10). This keeps the confidence interval honest, since the scored pages are then the random sample and not the pages typed first.
- Q: Does the app show two runs' scores side by side? → A: No. It scores one set of runs at a time, and scores are not saved (user decision, 2026-11-10). To compare runs, score each and compare the CSV files.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Check one document with a sample of pages (Priority: P1)

A user has extracted a 120-page PDF with one table that runs through the whole document and wants
more assurance than grounding gives. They open the review app, choose "Gold check", pick the
document, and draw a sample of 20 pages. For each page they read the page image, type the table into
the editor (or copy text from the page), name the columns, and mark the page done. They then ask for
the score and see how many cells, rows and pages of the extraction match what they typed.

**Why this priority**: this is the whole point of the feature, and everything else refines it.

**Independent Test**: with the synthetic fixture and a fake model, draw a sample, post a gold table
for each sampled page, and request the score. The numbers equal the faults injected into the fake
extraction (wrong cells, a dropped row, an extra row), and the definitions are printed beside them.

**Acceptance Scenarios**:

1. **Given** a project with a saved run of one document, **When** the user opens the gold check and draws a sample of 20 pages, **Then** 20 distinct pages of that document are listed as not started, the seed is shown, and drawing again with the same seed gives the same pages.
2. **Given** a sampled page, **When** the user types a table, names every column and marks the page done, **Then** the page shows as done, the progress line counts it, and reloading the app shows the same table.
3. **Given** every sampled page is done, **When** the user asks for the score, **Then** the report shows, for cells, rows and pages, the number correct, the number in the gold, the number extracted, recall, precision and accuracy, with a plain definition of each, and names the run it scored.
4. **Given** a sample where every typed page matches the extraction, **When** the user asks for the score, **Then** every figure is 100% and the list of differing cells is empty.
5. **Given** some sampled pages are not done, **When** the user asks for the score, **Then** the app says how many of the sampled pages are done and which are left, and shows no figures.

---

### User Story 2 - Pages with several tables, no table, or a table that continues (Priority: P1)

A user's document has pages with two tables, pages with none, and a table that continues over many
pages. For a page with two tables they add a second gold table on the same page and type each. For a
page with no table they mark it done with no table. For a continuation page they type the rows and
name the columns as they read them. The score pairs each gold table with the right extracted table
whatever order they were typed in and whatever the columns are called.

**Why this priority**: the user requires single and multi-table cases to work. Spec 004 made several
tables per document and per page a normal result, so a score that assumed one table per page would
be wrong for them.

**Independent Test**: run the fixture's multi-table documents through a fake model. Type the gold of
a shared page in both orders, once with the model's column names and once with different names. All
four scores are identical and correct.

**Acceptance Scenarios**:

1. **Given** a page that prints two tables, **When** the user adds two gold tables and marks the page done, **Then** the score pairs each with the extracted table whose values match it, and counts a gold table with no match as missed.
2. **Given** a page the user marked done with no table, **When** the extraction produced rows on that page, **Then** those rows count as extra and the page counts as wrong.
3. **Given** a page that prints a table the pipeline never found, **When** the user types it, **Then** all its rows count as missed and the page counts as wrong.
4. **Given** a gold table whose column names differ from the extracted table's names ("Amount ($)" against "Amount"), **When** scored, **Then** the columns are paired by their values and the report shows which gold column paired with which extracted column.
5. **Given** a table that continues over pages 4 to 9 and a sample that holds only pages 5 and 8 of it, **When** scored, **Then** the score covers those two pages and ignores the other pages of the table.
6. **Given** a page where the extraction merged two printed tables into one, **When** scored, **Then** the rows of the second printed table count as missed and the merged table's extra rows count as extra, so the structural error shows in the score.

---

### User Story 3 - Type quickly from the page (Priority: P2)

Typing 12 rows of text by hand is slow and error-prone. The editor works like a spreadsheet, and the
user can select text on the page image with the mouse to copy it into the table in one move: it goes
into the selected cell, and in "lock column" or "lock row" mode the selection then moves to the
next cell. Copied text comes out clean, on one line. The editor is blind: it starts empty and never
shows what the extraction produced.

**Why this priority**: the gold check is only worth doing if a person can finish it. It is not needed
for the first working score, so it follows the P1 stories.

**Independent Test**: unit tests of the pure editing and clean-up functions (offline, no browser),
plus a manual run in a browser with the demo project.

**Acceptance Scenarios**:

1. **Given** text selected on the page, **When** the mouse is released, **Then** the cleaned text is copied: newlines, tabs and repeated spaces become single spaces, a hyphen that ends a line is dropped and the halves joined, leading and trailing spaces and trailing periods (including dot leaders) are removed, and hyphens inside a line stay.
2. **Given** lock column mode and a selected cell, **When** the user selects text on the page, **Then** it is placed in the cell and the selection moves down the column. In lock row mode it moves right, wrapping to the next row. Turning one mode on turns the other off; clicking the lit one turns it off.
3. **Given** a lock mode, **When** the user holds Shift as they release the selection, **Then** the text is added to the cell after a "." (for multi-level column names) and the selection stays.
4. **Given** the editor, **When** the user uses any shortcut listed in FR-017, **Then** it behaves as in the VRA annotation app.
5. **Given** a copy, **When** the "Copied" notice appears, **Then** it does not cover the page or change the layout height.

---

### User Story 4 - Know how long it takes and turn the page (Priority: P2)

While typing, the user sees how long they have spent on the open page, how many sampled pages are
done, and about how long the rest will take. The clock only runs while the page is open and the app
is the window in front. If a scan is sideways, the user turns the page image to read it.

**Why this priority**: the timer tells a user what a sample size will cost before they commit to a bigger one, and a sideways page is unreadable without rotation. Neither blocks the first score.

**Independent Test**: unit tests of the clock and the estimate (pure functions, no browser), plus a manual run in a browser.

**Acceptance Scenarios**:

1. **Given** a page that is not done, **When** it is first opened, **Then** its clock starts, and it pauses when the tab is hidden or another window is in front and resumes when the app is back. Time so far is saved when it pauses.
2. **Given** the user marks a page done, **When** it is saved, **Then** the clock stops and the time is stored with the page. Reopening the page for correction resumes the clock.
3. **Given** at least one timed page is done, **When** the progress bar is shown, **Then** it says "N of M pages done · about X left · Y a page on average (K timed)", where X is the pages left times the average of the timed done pages, less what the open page has used so far. Before any timed page is done it says an estimate will appear after the first one.
4. **Given** a page's clock, **When** the user presses "Reset timer" and confirms, **Then** the time goes back to 0 and counts again.
5. **Given** a page image or the whole-PDF view, **When** the user turns it left or right by 90 degrees, **Then** the image and its selectable text turn together so selections still line up, and the turn is remembered for that page in this browser.

---

### User Story 5 - See exactly where the extraction differs (Priority: P2)

After scoring, the user wants to know what was wrong, not only how often. The app lists every cell
where the gold and the extraction are not an exact match, with the gold value, the extracted value,
the closest match level (normal, fuzzy or none) and the page. Opening an item shows that page. The same
lists are written as CSV files.

**Why this priority**: it turns a number into something the user can act on (a prompt change, a
setting, a bug report).

**Independent Test**: score a fake extraction with known differences and check the list holds exactly
those cells and the CSV files hold the same rows.

**Acceptance Scenarios**:

1. **Given** a score with differences, **When** the user opens the list, **Then** each difference shows the table, page, row, column, gold value, extracted value and match level.
2. **Given** a difference that only changes case, spacing, a dash style or a thousands comma, **When** scored, **Then** it is listed as a non-exact match at the "normal" level and does not count as an error.
3. **Given** the same score, **When** the user runs `quotable gold-report`, **Then** the same figures are printed and two CSV files are written: one line per page, and one line per differing cell.

---

### User Story 6 - Score another run against the same gold (Priority: P2)

The user changes the model or a setting and extracts the document again. They do not retype the gold:
they choose the new run and score it against the same pages. The app shows one score at a time and
saves none; to compare two runs they score each and compare the report files.

**Why this priority**: the gold is the expensive part. Reusing it is what makes the check useful for
choosing between models and settings.

**Independent Test**: save two runs of one fixture document (one with injected faults), type the gold
once, and score each run. Each score reflects only its own faults.

**Acceptance Scenarios**:

1. **Given** gold for a document and two runs of it, **When** the user chooses a run, **Then** the score uses that run, and by default the newest run of each document.
2. **Given** a PDF that was edited after the gold was typed, **When** the user scores a run of the edited file, **Then** the app says the document has no gold and scores nothing for it.

---

### User Story 7 - Several documents in one sample (Priority: P3)

A user with 40 PDFs wants one figure for the batch. They pick all of them, draw a sample, and get
pooled figures plus a line for each document.

**Why this priority**: useful for corpora like the VRA one, but one document is enough for a first
version.

**Independent Test**: draw a sample of 10 pages from three fixture documents of different lengths.
Every document has at least one page, longer documents have more, and the same seed repeats the draw.

**Acceptance Scenarios**:

1. **Given** three documents and a sample of 10, **When** drawn, **Then** each document has at least one page and the rest are split in proportion to the square root of each document's page count, so long documents get more pages without crowding out short ones.
2. **Given** a pooled score, **When** shown, **Then** the pooled figures come with one line per document and one line per extracted table.

---

### Edge Cases

- A sampled page's PDF is missing or has changed since the run: the page cannot be shown. The app says so and keeps the gold already typed. That page cannot be done, so scoring stays unavailable until the PDF is back or a new sample is drawn without that document.
- A page marked done with a gold table that has named columns and no rows: it counts as a table with zero rows, so every extracted row on that page is extra.
- A typist leaves untouched empty rows at the bottom: they are not saved. A row the typist blanked on purpose in the middle is kept.
- Two columns print the same header: the typist must still give them distinct names (for example "Amount" and "Amount 2"). Pairing does not depend on the names.
- The page is opened in two browser tabs: the later save wins, and the earlier tab is not silently overwritten without the user seeing a saved indicator.
- The server stops while typing: the app shows a loud warning, keeps the unsaved page in the browser, retries, refuses to switch pages while unsaved, and asks before the tab closes.
- A cell with more characters, or a table with more rows or columns, than the fixed limits: the save is refused with a message that names the limit. Nothing typed is lost on screen.
- A document with an unreadable text layer that was OCR'd: copy-from-page copies the OCR text of the pages where the chosen run kept it (the pages that run found a table on). On other pages it offers the PDF's own text, which may be empty, and the typist types by hand. The typist reads the image, so a wrong word in the OCR text should be corrected by hand.
- The same PDF under two file names: one document (same content hash), one set of gold.
- Garbled input in a cell (markup, very long text): shown and stored as plain text, never interpreted.
- A page that is printed sideways: the user turns the view to read it. The turn only changes the view; extraction and scoring never depend on it.
- A page reopened after being marked done: its clock resumes from the stored time. A page finished before this feature stored time shows "--" and is left out of the average.
- Score requested when a sampled document has no chosen run (for example its runs were deleted): that document is listed as "not scored" and left out of the totals, and the report says so at the top.

## Requirements *(mandatory)*

### Functional Requirements

#### Optional and separate

- **FR-001**: The gold check MUST be optional. `extract_tables`, its output, `records()`, the DataFrames, the cache, the cost log and saved runs MUST be unchanged by this feature and by whether it is used.
- **FR-002**: The gold check MUST NOT make a model request. Scoring and the editor MUST work with no network and no API key.
- **FR-003**: The gold check MUST be part of the review app (`quotable review`) and follow the app's rules from spec 013 section B: local only, host and origin checks, untrusted text shown only as text, files reached by run id and page number, no network access from the browser.
- **FR-004**: The gold check MUST only write its own gold files. It MUST NOT change runs, the cache, the cost log, the review verdicts or the PDF.

#### Sample

- **FR-005**: The user MUST be able to choose one or more documents that have a saved run, and a sample size. The default size is 20 pages, or every page when the chosen documents have fewer.
- **FR-006**: The sample MUST be drawn at random from every page of the chosen documents, including pages where no run found a table.
- **FR-007**: Each chosen document MUST get at least one page, and the remaining pages MUST be split across documents in proportion to the square root of their page counts. A page MUST NOT be drawn twice.
- **FR-008**: The draw MUST be seeded. The seed MUST be shown, and the same documents, size and seed MUST give the same pages.
- **FR-009**: Drawing a new sample MUST ask for confirmation when a sample exists. Gold already typed MUST be kept and reused if its page is drawn again. Pages no longer in the sample MUST NOT be scored.
- **FR-010**: The sampled pages MUST be listed with their document, page number and status (not started, started, done), with a progress line ("N of M pages done") and a way to jump to any page.

#### Typing the gold

- **FR-011**: For a sampled page, the app MUST show the page image next to the editor, and MUST offer a whole-PDF view that stacks every page of the document with the same selectable text, so copying and the lock modes work there too. The user MUST be able to turn the page image (and the whole-PDF view) left or right by 90 degrees, the selectable text MUST turn with it, and the turn MUST be remembered for that page in this browser. The user MUST be able to zoom (buttons, fit, trackpad pinch) and hide the page list.
- **FR-012**: A page MUST be able to hold any number of gold tables. The user MUST be able to add and remove gold tables on a page. Marking a page done with no gold table MUST mean "this page has no table".
- **FR-013**: A gold table is a list of named columns and rows with one cell per column. All cell values MUST be stored as typed, as text.
- **FR-014**: The editor MUST be blind, as the VRA annotation app is. A page that is not done opens with one unnamed column and 20 empty rows to type into; those empty rows do not make the page "started". The extraction (values, statuses, row or column counts) MUST NOT be shown anywhere in the gold check's entry screens, and no pre-filled mode exists.
- **FR-015**: Marking a page done MUST require every column of every gold table to be named, with distinct names within a table. If it fails, the app MUST say why and leave the page not done.
- **FR-016**: Untouched empty rows at the bottom of a gold table MUST NOT be saved.
- **FR-017**: The editor MUST keep every keyboard and mouse behavior of the VRA annotation app's table editor (⌘ is Ctrl on Windows and Linux):
  - Arrow keys move the selection; Shift+arrows extend it to a block; ⌘+arrow jumps to the table's edge; ⌘A selects the whole table; clicking or dragging cells selects them; clicking a row number selects the row (Shift extends); dragging past an edge scrolls the table.
  - Tab and Shift+Tab move right and left, wrapping to the next or previous row.
  - Typing a character replaces the cell and starts editing; Enter, F2 or a double-click edits the cell as it is; Enter saves the edit and moves down; Tab saves it and moves right; Escape cancels it; Option+Enter, Shift+Enter or ⌘+Enter adds a line break inside the cell; arrow keys after typing over a cell save it and move on.
  - Delete or Backspace clears the selected block.
  - ⌘C, ⌘X and ⌘V copy, cut and paste tab-separated blocks (cells with tabs, line breaks or quotes are quoted as spreadsheets do), and a paste adds columns when it is wider than the table.
  - ⌘Z undoes, and ⇧⌘Z or ⌘Y redoes, with history kept for the open page.
  - ⌘D fills down and ⌘R fills right; the fill handle at the selection's corner copies the block along the drag, and a double-click on it fills down as far as the longest other column runs. Values are copied as they are; numbers do not become a series.
  - Typing in the empty bottom row starts a new row; "New row" and "Add column" buttons, and a delete button on each row and column (asking first when a column holds values), are also available.
  - Home, End, Page Up and Page Down do nothing to the table or the viewer.
- **FR-018**: The user MUST be able to select text on the page image with the mouse and have it copied, cleaned as in User Story 3 scenario 1. The highlight MUST stay until the next click on the page. Selecting the same text again without a new selection MUST NOT copy or paste it twice.
- **FR-019**: The editor MUST offer a **lock column** mode and a **lock row** mode with the behavior of the VRA app's fast column and fast row modes (only one on at a time; clicking the lit one turns it off):
  - Lock column: text selected on the page goes into the selected cell and the selection moves down. On reaching the last row that the tallest other column fills, it moves to the top of the next column. It never fills the column-name row; it starts at the first data row.
  - Lock row: text goes into the selected cell and the selection moves right, wrapping to the first cell of the next row. It may fill the column names, and on the last column name it adds a column and moves into it so a header can be copied across. Tab from the last column adds a column.
  - Holding Shift as the selection is released adds the text to the cell after a "." and stays on the cell. The target cell is tinted while Shift is held.
  - Each paste is one undo step, and undo returns to the cell it went into.
  - The buttons, titles and messages use the words "lock column" and "lock row" (the VRA names "fast column" and "fast row" do not appear).
- **FR-020**: Every key pressed while the app is in front MUST go to the table, wherever focus was last clicked (the page, the page list, a button), so nothing scrolls the viewer or lists. Arrow keys and ⌘ combinations go to the table too. Only a text box being typed in keeps its keys, and browser shortcuts such as opening a tab, reloading or going back are left alone.
- **FR-020a**: Each page MUST have a work clock. It starts when a page that is not done is first opened, counts only while the page is open and the app is the window in front, pauses when the tab is hidden or another window is in front (saving the time so far), stops when the page is marked done, and resumes if the page is reopened for correction. A "Reset timer" button MUST set it to 0 after confirmation. The time MUST be stored with the page.
- **FR-020b**: The progress bar MUST show "N of M pages done" and, once a timed page is done, "about X left · Y a page on average (K timed)". X is the pages left times the average time of the timed done pages, less the time the open page has used (never more than the average). Before that it says the estimate appears after the first timed page is done. It updates every second.
- **FR-021**: The editor MUST save automatically shortly after each change. A save that cannot reach the server MUST show a loud, persistent warning, keep the page's table in the browser, retry, refuse to switch pages while unsaved, and ask before the tab is closed. Typed work MUST NOT be lost without the user seeing that.
- **FR-022**: The save MUST refuse a page beyond fixed limits with a message naming the limit: 10 tables per page, 40 columns per table, 400 rows per table, 2,000 characters per cell and 2 MiB for the whole save.

#### Scoring

- **FR-023**: A score MUST be available only when every page of the current sample is marked done. Otherwise the app and the command MUST say how many are done and which are left, and show no figures. When it is available, every sampled page MUST be scored. For each document in the sample, the score MUST use one chosen run, the newest run by default, and the report MUST name every run used. The app MUST show one score at a time. Scores are computed on demand and MUST NOT be stored.
- **FR-024**: A page MUST be compared with every row of every table of the chosen run on that page, in the form `records()` returns after the recheck, merge and audit.
- **FR-025**: On a page, gold tables MUST be paired one to one with extracted tables by how well their values match, not by the order typed or by column names. A gold table without a partner MUST count as missed. The rows of an extracted table without a partner MUST count as extra.
- **FR-026**: Within a paired table, columns MUST be paired by normalized name where the names match, and the rest by how well their values match, so the typist never has to copy the model's column names. A gold column with no partner MUST have all its cells missed. An extracted column with no partner MUST have its filled cells counted as extra. The report MUST show how every column was paired.
- **FR-027**: Within a paired table, gold rows and extracted rows MUST be paired one to one by best overall similarity. A pair below a minimum similarity of 50% MUST NOT be a match: the gold row counts as missed and the extracted row as extra.
- **FR-028**: Every cell where the gold or the extraction has text MUST be compared at three levels:
  - **exact**: equal after trimming and collapsing whitespace.
  - **normal**: also equal ignoring soft hyphens, case, `$` signs, thousands commas, curly against straight quotes, two single quotes against one double quote, dash style, trailing periods, a line-break hyphen ("Expan- sion"), Unicode compatibility forms, and the order of `;`-separated items.
  - **fuzzy**: normalized similarity of at least 90%.

  A cell made only of dots or dashes MUST be compared as it is (not treated as blank); a trailing period is dropped only when other text remains, so a cell of only dots stays as it is.
- **FR-029**: The score MUST report, for cells, rows and pages, at the normal level (the headline level; a cell that is correct only at the fuzzy level is not correct): the number correct, the number in the gold, the number extracted, recall (correct / gold), precision (correct / extracted) and accuracy (correct / in either). A cell is correct when the gold has text and the extraction passes. A row is correct when it is paired and every cell is correct. A page is correct when every row of every table on it is correct and no table or row is missed or extra. A page that has no table in the gold or in the extraction MUST NOT be counted.
- **FR-030**: The report MUST also give the counts of paired, missed and extra rows; exact, normal and fuzzy cell accuracy; and the numbers of missed cells (gold text, extraction blank) and extra cells (extraction text, gold blank). It MUST print the definitions beside the figures.
- **FR-031**: The report MUST break the figures down per document and per extracted table, and list gold tables that no extracted table matched, so a weak table in a multi-table document stands out.
- **FR-032**: When the scored sample is of one document, the report MUST show the share of counted pages that are correct with a confidence interval at 95%, using the finite-population correction (the sample is a share of that document's pages), and say it is an estimate for that document. For a sample of several documents it MUST show per-document figures and pooled counts and MUST NOT show an interval. Cell and row figures MUST NOT have an interval, and the report MUST say why (cells on one page are not independent).
- **FR-033**: The app MUST list every cell that is not an exact match with its table, page, row, column, gold value, extracted value and closest match level, and MUST link each to its page.
- **FR-034**: The command `quotable gold-report` MUST print the same report, and write one CSV file with a line per page and one with a line per non-exact cell. It MUST accept `--dir PATH` (the project's `.quotable/` folder, as `cost-report` and `review` do), `--run ID` (repeatable) to choose runs, and `--out DIR` for the two files (default: `reports/` in the project folder, which git ignores). A usage error exits 2; scoring while sampled pages are not done exits 1 with a message that says how many are done.
- **FR-035**: Gold typed for a PDF whose content hash differs from a run's document MUST NOT be applied to that run. The report MUST say the document has no gold.

#### Storing the gold

- **FR-036**: Gold MUST be stored in the project's `.quotable/` folder, in its own folder, keyed by document content hash and page. It MUST survive deleting the cache, the runs and the review verdicts. The gold folder MUST NOT be ignored by git, so the user can commit it; the rest of `.quotable/` stays ignored. When the gold check first writes gold and `.quotable/.gitignore` is exactly quotable's own `*`, it MUST add an exception for the gold folder. If that file has other content, it MUST be left as it is and the app and command MUST tell the user the gold folder may be ignored. Nothing is ever committed for the user.
- **FR-037**: Each page's record holds its tables, columns, rows, done flag, seconds spent and last-saved time. The turn applied to a page's view is kept in the browser, not here. The latest record for a page wins. The format MUST be plain text readable without quotable.
- **FR-038**: A write MUST be safe against a crash or two tabs: earlier gold MUST NOT be lost or half written.
- **FR-039**: The README MUST describe the workflow and its limits, including that text copied from the page comes from the PDF's text layer, so a text-layer error can be copied into the gold, and that the gold folder is not git-ignored and holds text copied from the PDF (check the PDF's licence before committing it to a public repository). `AGENTS.md` MUST be updated in the same change.

### Key Entities *(include if feature involves data)*

- **Gold sample**: the chosen documents, the size, the seed and the sampled pages. One at a time per project.
- **Gold page**: one page of one document (by content hash) with zero or more gold tables and a done flag. A done page with no gold tables says "no table here".
- **Gold table**: named columns and rows typed by a person for one printed table on one page.
- **Table pairing**: for one page, which gold table matches which extracted table, and for each pair, which gold column matches which extracted column and which gold row matches which extracted row.
- **Score report**: the figures of FR-029 to FR-032 for a set of runs, the list of non-exact cells, and the two CSV files.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: With a saved run, a user can draw a sample, type gold and read a score without leaving the browser and without installing anything beyond quotable. An offline test drives that whole path on a fixture document.
- **SC-002**: On the synthetic fixture with faults injected into a fake extraction (a known number of wrong cells, one dropped row and one extra row), the reported counts of wrong, missed and extra cells and rows equal the injected numbers exactly.
- **SC-003**: For a fixture page with two tables, the score is identical whether the gold tables are typed in one order or the other, and whether their columns carry the model's names or different names.
- **SC-004**: The scorer gives the same numbers as the VRA scorer on the cases in the VRA project's `tests/test_gold_eval.py`, except where this spec deliberately differs (dots and dashes are not blanked).
- **SC-005**: A reviewer can type and finish 20 pages of about 12 rows each in under an hour, with the copy-from-page features on. The app's own timer reports it (the VRA average was about 130 seconds a page).
- **SC-006**: After a save shows "Saved", stopping and restarting the server and reloading the app shows exactly the saved gold. A save that failed is always visible to the user.
- **SC-007**: A project where the gold check is never opened is byte-identical in `.quotable/runs/`, `.quotable/cache/` and `.quotable/cost/`, and `extract_tables` returns the same output. Using the gold check adds no line to the cost log.
- **SC-008**: Every cell that is not an exact match appears once in the differences list, and following its link opens the right page.

## Out of scope

- **Pre-filling the editor from the extraction.** The editor is blind (user decision).
- **A public Python function for scoring.** Scoring is read in the review app and with `quotable gold-report` only (user decision). Nothing is added to `quotable/__init__.py`.
- **Gold for extra fields** (spec 010): values printed outside the table. They are scored by the recheck and by spec 013 verdicts. A later spec can add them.
- **Using the gold to change anything**: it does not correct output, tune prompts or choose a model. It is a measurement.
- **Breakdown by grounding status** (does an `exact` cell ever turn out wrong?). A likely follow-up, because it shows whether unflagged cells can be trusted.
- **A second typist, agreement between typists, or review of the gold.**
- **A running or partial score** while the sample is incomplete (user decision).
- **Drawing a sample from PDF paths before any run exists** (user decision). Gold is keyed to the PDF's content hash, so a later spec can add it without changing stored gold.
- **Adding single pages to the sample by hand**, and growing a sample. Draw a new one (the typed gold is kept).
- **From the VRA project**: matching its document families (original and updated versions of one document).
- **Remote or shared use**, as in spec 013.
- **Extracting rotated pages.** Page orientation is not ported to quotable (see the README). Only the gold check's view can be turned.

## Assumptions

- The user has at least one saved run (spec 013) of each document to check. Without one, the gold check says how to make one.
- The user has the PDFs at the paths the runs recorded. If a PDF is missing, its pages cannot be shown, and its gold cannot be typed until it is back.
- Typed gold is the truth. A person can be wrong, and the gold may differ from the page; the differences list is where such cases are noticed.
- The review app's page rendering, text overlay, local-only server rules and visual design are reused rather than rebuilt. Page images are sharp enough to read small print.
- The sampling unit is the page. Documents are the strata. The VRA project also grouped a document's original and updated versions into families; that is specific to it and is not carried over.
- A typical sampled page has 5 to 50 rows and at most a few tables. The fixed limits are generous multiples of that.
- The numbers the VRA project chose, a 50% row-pairing minimum and a 90% fuzzy cutoff, were first guesses there. They are carried over as defaults and can be revisited in the plan once they are tried on the synthetic fixture.
- Column pairing by values, not only names, is a deliberate improvement over the VRA scorer, which could rely on a fixed schema. quotable's column names come from the model, so names alone would give false misses.
- The first version scores the output of the chosen run as `records()` returns it. It does not score intermediate steps such as the first pass before the recheck.
