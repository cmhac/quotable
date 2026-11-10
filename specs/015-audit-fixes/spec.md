# Feature Specification: Audit fixes

**Feature Branch**: `spec/015-audit-fixes`

**Created**: 2026-11-10

**Status**: Draft

**Input**: User description: "Fix findings 2, 3, 4, 6, 7, 9 and 11 of the 2026-11-10 ponytail audit. Ignore the license finding for now."

The seven items come from the audit report. Each user story below names the audit finding it fixes
in its heading. Terms used in this spec:

- **Recheck**: the last pipeline step. Cells that did not match the PDF's text layer go back to the
  model once. It exists as a step for table cells and, separately, for extra-field values.
- **Review app**: the local web app started by `quotable review`.
- **Run**: one saved call of `extract_tables`, kept in `.quotable/runs/`.
- **Review queue**: the list of cells the review app asks a person to check, drawn from the newest
  run of each document.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - The recheck stays within the request limit (audit finding 3) (Priority: P1)

An analyst extracts a long table (100+ pages) from a PDF, and many pages have cells that did not
match the text layer. Extraction, the omission audit and the extra-field second looks all send at
most 4 model requests at the same time, so provider rate limits are not hit. The recheck does not:
it sends one request per flagged page, all at once, so a 150-page table can put about 150 image
requests in flight together, at the very end of an expensive run.

**Why this priority**: it can fail a large run at its last step, and it is the only stage that
breaks the limit the other stages keep.

**Independent Test**: run the whole pipeline on a generated table of 20 pages in which every page
has a flagged cell, with a fake model that records how many requests are in flight at once. The
highest number seen must be 4 or less. The returned tables must equal those of the same run before
the change.

**Acceptance Scenarios**:

1. **Given** a table whose flagged cells are on 20 pages, **When** the recheck runs, **Then** no
   more than 4 model requests are in flight at any moment, and every page is still rechecked.
2. **Given** a document with three tables that all have flagged cells, **When** the rechecks run,
   **Then** the limit of 4 applies to all three together, not to each table.
3. **Given** extra fields whose values did not match, **When** their recheck runs, **Then** it
   follows the same limit.
4. **Given** the same inputs as before the change, **When** the pipeline runs, **Then** the same
   requests are made with the same content, the cache keys are unchanged, and the returned tables
   are identical.

---

### User Story 2 - The review app renders page images one at a time (audit finding 2) (Priority: P1)

A reviewer works in the review app. The browser often asks for several page images at once (the
page view and a cell view). The app answers each request on its own thread, and the PDF library it
uses is documented as unsafe to call from several threads at once. A crash would end the server
and lose whatever the reviewer typed but had not yet saved.

**Why this priority**: a crash of the tool a reviewer is working in, with unsaved input lost.

**Independent Test**: start the app on the demo project and request 20 page images at the same
time, some for the same page. Every answer is a valid image, and an instrumented render shows two
renders never overlap.

**Acceptance Scenarios**:

1. **Given** the review app on a project with a PDF, **When** the browser requests several page
   images at the same time, **Then** every request gets the correct image.
2. **Given** several requests in flight, **When** they reach the render step, **Then** at most one
   render runs at any moment and the others wait.
3. **Given** a render that fails (the PDF cannot be read), **When** the next request arrives,
   **Then** it is not blocked, and the failed request still answers "the PDF cannot be read" as
   before.

---

### User Story 3 - The review queue stays quick as documents pile up (audit finding 4) (Priority: P2)

A reviewer works through a project with a few dozen documents. Every queue refresh and every saved
verdict loads the newest run of each document, but the app keeps only 4 parsed runs in memory. With
more documents than that, every request re-reads and re-parses the run files from disk. On the
8-document demo project the second queue request (0.40 s) was not faster than the first (0.33 s).

**Why this priority**: the app slows with each document added, and the reviewer feels it on every
click.

**Independent Test**: on a project of 50 generated runs, request the queue twice. The second
request reads no run file from disk. Then change one run file on disk and request again: only that
run is read again, and the answer reflects the change.

**Acceptance Scenarios**:

1. **Given** a project with up to 50 documents and no change on disk, **When** the queue or a
   verdict save needs every document's newest run a second time, **Then** no run file is read.
2. **Given** a run file that changed on disk after it was loaded, **When** it is needed again,
   **Then** the new content is used.
3. **Given** more documents than the cache holds, **When** the queue is requested, **Then** the
   answer is correct, only slower.
4. **Given** the queue and the verdict API, **When** called as before, **Then** their answers are
   unchanged.

---

### User Story 4 - Install without the two DataFrame libraries (audit finding 11) (Priority: P2)

A user installs `quotable` to get tables out of PDFs as Python objects (`records()`), or uses only
one of pandas or polars. Today both are installed with the package, although they are used only by
`to_pandas()` and `to_polars()`. After this change, a plain install has neither, and the user adds
the one they want.

**Why this priority**: it shrinks the default install and is a visible change to how the package is
installed, so it should be decided and recorded.

**Independent Test**: in a fresh environment with only the base package, `import quotable` and the
whole pipeline work (with a fake model), and `to_pandas()` fails with a message that says what to
install. With the extra installed, the frame tests pass.

**Acceptance Scenarios**:

1. **Given** the base package without pandas or polars, **When** a table is extracted and
   `records()` is used, **Then** it works.
2. **Given** no pandas, **When** `to_pandas()` is called, **Then** an `ImportError` says that
   pandas is missing and shows the install line `pip install "quotable[pandas]"`. The same holds
   for polars and `quotable[polars]`.
3. **Given** `quotable[pandas]` or `quotable[polars]` is installed, **When** the matching method is
   called, **Then** it returns the same frame as before.
4. **Given** the development environment, **When** the tests run, **Then** both libraries are
   present and every existing frame test passes.

---

### User Story 5 - Notebook users know how to call the library (audit finding 9) (Priority: P3)

A data analyst calls `extract_tables(...)` in a Jupyter notebook. The synchronous function starts
its own event loop, and Python refuses that inside a notebook, which already runs one. The error
does not say what to do instead.

**Why this priority**: it is a documentation gap; the working answer (`await
extract_tables_async(...)`) already exists.

**Independent Test**: read the README. It tells a notebook user to await `extract_tables_async`,
and says why.

**Acceptance Scenarios**:

1. **Given** the README, **When** a notebook user looks for how to call the library, **Then** one
   short passage says to use `await extract_tables_async(...)` and that `extract_tables` cannot be
   called while an event loop is already running.
2. **Given** a test that awaits `extract_tables_async` inside a running loop with a fake model,
   **When** it runs, **Then** it passes, so the README's advice is true.

---

### User Story 6 - Maintainers: no duplicate test file, no unused merge setting (audit findings 6 and 7) (Priority: P3)

A maintainer changes the merge step's tests. Spec 012 moved the tests into folders that mirror the
package, but left the old file behind. `tests/test_merge_checks.py` and
`tests/steps/test_merge_checks.py` are byte-identical (35 test functions each, 55 collected tests because some are parametrized) and both run, so the test
count is inflated by 55 and an edit to one copy is hidden by the other. Separately, the merge step
has a setting (`Rules.equal_share`, the "half-equal header" rule) that is off by default, was found
harmful by spec 007's own results, and is used only by a test and a scoring script.

**Why this priority**: housekeeping with no user-visible change, done once so it does not drift.

**Independent Test**: only one file named `test_merge_checks.py` exists; the suite passes with 55
fewer tests from that removal; the merge step gives the same decisions on every fixture document.

**Acceptance Scenarios**:

1. **Given** the repository, **When** the test files are listed, **Then** no two test files share a
   name, and `tests/steps/test_merge_checks.py` remains.
2. **Given** the default merge rules, **When** the merge step runs on every document of the
   synthetic fixture, **Then** every decision is the same as before this change.
3. **Given** the half-equal rule is removed, **When** the merge code is read, **Then** it holds no
   setting, function, failure reason or test for it, and the fixture files are unchanged.

---

### Edge Cases

- A run with no flagged cells makes no recheck request (as before); the limit does not change that.
- `max_requests` is reached during the recheck: `BudgetExceededError` is raised as before. Waiting
  for a free slot must not let more new requests start than the cap allows.
- A render in the review app fails or is cancelled while it holds the render lock: the lock is
  released, and later renders work.
- The same page is requested twice at once: both get the same image.
- A saved run is deleted or damaged while the review app runs: the answer is "no such run" or "run
  cannot be read", as before, and a stale parsed copy is not served.
- A project has more run data than the budget holds (50 documents of several MiB each): slower,
  never wrong. The memory the cache can take has an upper bound (FR-007). A single run bigger than
  the whole budget is still kept, alone, while it is the one in use.
- Only pandas, only polars or neither is installed: each method works exactly when its library is
  present. `import quotable` loads neither library, as before.
- Saved runs and stored decisions written by 0.1.0 or by the current code are read as before. Nothing
  stored depends on the half-equal rule's failure reason.

## Requirements *(mandatory)*

### Functional Requirements

**Recheck request limit (story 1)**

- **FR-001**: During a run, no more than 4 model requests MUST be in flight at the same time. That
  includes the recheck of table cells and the recheck of extra-field values, not only extraction,
  the audit and the second looks.
- **FR-002**: The limit MUST be shared by all tables and all stages of one run, not applied per
  table.
- **FR-003**: Which requests are made, their content, their cache keys and how their answers are
  applied MUST NOT change. The same inputs MUST give identical tables.

**Review app renders (story 2)**

- **FR-004**: The review app MUST run at most one page render at a time in its process; other
  renders wait.
- **FR-005**: A render that fails MUST release the wait and MUST NOT block later renders. Its
  failure MUST still be reported as before.
- **FR-006**: Every concurrent request for a page image MUST receive the correct image.

**Review queue cache (story 3)**

- **FR-007**: The review app MUST keep parsed runs in memory up to a fixed size budget instead of a
  fixed count of 4, so that repeated queue and verdict requests on an unchanged project read no run
  file. The budget is 64 MiB of run files on disk (about 320 MB of memory once parsed, measured at
  about 5 times the file size). The newest runs of 50 documents fit if their files average 1.3 MiB
  or less. Beyond the budget, the run used least recently is dropped.
- **FR-008**: A run whose file changed (size or modification time) MUST be read again before it is
  used. Answers MUST NOT be stale.
- **FR-009**: The most memory the cache can hold MUST be stated (done in FR-007, measured on the
  largest demo run: 5.7 MB of files, 28.5 MB parsed). The queue and verdict answers MUST NOT change.
- **FR-009a** *(added during planning, after profiling a queue request)*: A queue request MUST build
  the list of reviewable items once. Today it builds the list twice, once for the status counts and
  once for the queue, and that is 58% of a repeated request on the demo project (reading runs from
  disk is 39%).

**DataFrame libraries (story 4)**

- **FR-010**: pandas and polars MUST NOT be required dependencies. Each MUST be an optional extra of
  the package, named `pandas` and `polars`, with the same version ranges as today.
- **FR-011**: `to_pandas()` and `to_polars()` MUST raise `ImportError` with a message that names the
  missing library and the install line for its extra when that library is not installed.
- **FR-012**: The development environment MUST include both libraries so the existing frame tests
  run. `import quotable` MUST load neither.
- **FR-013**: The README MUST replace "pandas and polars are installed with quotable" with the
  install lines for the extras. Spec 008's requirement 7 (base dependencies) is replaced by this
  requirement; spec 008 is not edited.

**Notebook note (story 5)**

- **FR-014**: The README MUST tell notebook users to `await extract_tables_async(...)` and say that
  `extract_tables` cannot run while an event loop is already running. A test MUST show that
  `extract_tables_async` works inside a running loop.

**Housekeeping (story 6)**

- **FR-015**: `tests/test_merge_checks.py` MUST be deleted; `tests/steps/test_merge_checks.py` is
  the one copy.
- **FR-016**: The half-equal merge rule MUST be removed: the `equal_share` setting, `half_equal_ok`,
  the `half_equal` failure reason, the unit test for them, and the `equal_share` rows of the
  scoring script (`just score-merge`). The synthetic fixture MUST stay byte-identical (its
  documents and their `half_equal` labels are kept); the test that checks those cases exist is
  reworded so it no longer says they decide a rule. Spec 007's half-equal score rows can no longer
  be reproduced; spec 007 keeps them as history (decided in Question 1, option A).
- **FR-017**: The merge step's decisions under the default rules MUST be identical before and after,
  for every document of the synthetic fixture.

**Across the change**

- **FR-018**: The public API (`quotable/__init__.py`), prompts, cache keys and the saved-run format
  MUST NOT change (constitution, principle IV). The only user-visible changes are the install
  extras and the new `ImportError` message.
- **FR-019**: `AGENTS.md` MUST be updated in the same change: project state (spec 015, the new test
  count, pandas and polars as extras) and anything in the file structure that changed.
- **FR-020**: New non-trivial logic MUST ship with a test (constitution, principle III): the
  request limit, the render lock, the run cache, and the `ImportError` message.

### Out of scope

The licence finding (the user chose to ignore it for now); the CSV formula-injection finding (5);
the slow fuzzy match (8); holding every page image in memory (10); pruning `.quotable/runs/`; the
overwritten `drafts.json.bad` backup.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: On a 20-page table with a flagged cell on every page, the most model requests ever in
  flight during a whole run is 4 or less (before: about 20 during the recheck).
- **SC-002**: With 20 page-image requests made at the same time, all 20 answers are valid images
  and no two renders overlap.
- **SC-003**: On a project of 50 runs that fit the budget, with no change on disk, the second queue
  request reads 0 run files (before: every run beyond the first 4 is read again). On the 8-document demo project, a
  repeated queue request takes at most half the time it takes on `main` (about 0.4 s there), both
  measured on the same machine.
- **SC-004**: A base install has neither pandas nor polars, and `import quotable` plus a full fake-
  model run succeed in it. With each extra installed, all existing frame tests pass.
- **SC-005**: Ruff, ty and the offline tests pass. Removing the duplicate file lowers the test
  count by exactly 55. Each other change in the count is a test this spec removes or adds, listed in
  the tasks.
- **SC-006**: A notebook user finds the notebook advice and the extra install lines in the README
  without reading any other file.
- **SC-007**: Merge decisions on all fixture documents under the default rules are the same as
  before the change.

## Assumptions

- "A few dozen documents" is the load that matters for the review app: one reviewer, one project.
- The audit's timings (0.33 s and 0.40 s for the queue on 8 documents) were measured once on a
  development machine. Planning profiled a repeated request (0.47 s under the profiler): reading
  runs is 0.18 s, building the item list twice is 0.27 s. That is why FR-009a was added.
- The crash in finding 2 was not reproduced; the requirement follows the PyMuPDF documentation,
  which says the library does not support use from several threads.
- The rate-limit failure in finding 3 was not reproduced against a real provider. The requirement
  is to make the recheck follow the limit the other stages already keep.
- The next release is a minor version (0.x), because installing without pandas and polars is a
  change for people who relied on them coming with the package. Release notes are outside this spec.
- Nothing stored on disk (saved runs, verdicts, cost log, cache) holds the half-equal rule's name.
  The plan confirms this before the rule is removed.
- Extras are named `pandas` and `polars`, one per library, with no combined extra.
- The synthetic fixture, if kept as it is, stays byte-identical to what `just synthetic` generates.

## Decisions

**Question 1 (decided: option A)**: what happens to the half-equal rule's fixture cases and scoring
rows? Remove the rule, its setting, its unit test and the scorer's `equal_share` rows. Keep the
fixture documents as they are, and keep the test that they exist, reworded. The options not taken
were to leave the rule in place (B) and to remove the 50+ cases that exist for it and regenerate
the fixture (C).

## Results

### Baseline on main, 2026-11-10 (before any change on this branch)

- Repeated `get_queue` on the 8-document demo project (`build/review-demo`, 3 runs after one warm-up): 0.372 s, 0.319 s, 0.350 s.
- `python -m tests.score_merge`, default rules (`equal_share=0.00 tol=10 min_cells=5 shape=0.8 words_apart=False`): harmful 0, (resid) 4, broken 0, missed 39. `git status` under `tests/data/synthetic/` is clean.

### After story 3 (review queue)

- Repeated `get_queue` on the same demo project, same machine: 0.110 s, 0.097 s, 0.105 s (baseline 0.372, 0.319, 0.350). That is about 3.4 times faster, so SC-003 ("at most half") is met.
- On a project of 10 more copied documents, the second queue request reads 0 run files (before: the 15 runs beyond the first 4 were read again).
- Memory: the run cache holds up to 64 MiB of run files (about 5 times that parsed, measured on 2026-11-10 on the 3,024-row run: 5.7 MB of files, 28.5 MB parsed).

### After story 6 (merge rule removed, duplicate test file removed)

- `python -m tests.score_merge --detail`, default rules: harmful 0, (resid) 4, broken 0, missed 39, the same as the baseline. The 54 lines of per-document disagreements after the "Defaults" header are identical before and after (`diff` empty). `git status` under `tests/data/synthetic/` is clean, so `just synthetic` and its freshness test are untouched.
- Spec 007's half-equal score rows (rows 215 and 216 of its table) can no longer be reproduced; spec 007 keeps them as history (Question 1, option A).
- Tests removed: the duplicate file's 35 test functions (55 collected tests), and 2 of the half-equal rule (`test_equal_share_is_a_setting`, `test_half_equal_ok_at_the_edges`). One more, `test_fewer_than_half_equal_fails_only_when_the_rule_is_on`, was rewritten as `test_a_pair_with_few_equal_header_words_still_merges` (a pair with no equal header position still merges under the default rules). The plan had counted one removed test; there were two.

### Final state (2026-11-10)

- Offline suite: **2,661 passed** (`uv run pytest -n 3`), `ruff check`, `ruff format --check` and `ty check` clean (also through `pre-commit run --all-files`). No live or OCR test was run, nothing was spent, nothing was pushed.
- Test count: 2,704 − 55 (the duplicate file's collected tests; it has 35 test functions, but several are parametrized) − 2 (the half-equal rule's `test_equal_share_is_a_setting` and `test_half_equal_ok_at_the_edges`) + 14 new = 2,661. New tests: `tests/test_recheck_limit.py` (1), `tests/steps/test_recheck.py` (3, the last added by convergence task T034: two tables share one limit), `tests/steps/test_extra_fields_recheck.py` (1), `tests/review/test_render_lock.py` (2), `tests/review/test_run_cache.py` (5), `tests/test_frames.py` (2, one per library). One more test was rewritten in place (`test_a_pair_with_few_equal_header_words_still_merges`).
- The earlier statement "the suite drops by exactly 35" was wrong in the spec, plan and research (it counted functions, not collected tests). They now say 55.

| Audit finding | Result | Proof |
|---------------|--------|-------|
| 2 (render lock) | fixed | `test_render_lock.py`: six clients at a time over 20 requests, never two renders at once (6 at once on the unchanged code); a failed render does not block the next. The test uses six at a time because the server's default backlog of 5 resets 20 simultaneous connections, and a browser opens six per host. The crash itself was never reproduced. |
| 3 (recheck limit) | fixed | `test_recheck_limit.py`: with the run's limit set to 1, the highest number of requests in flight over a whole run is 1 (4 on the unchanged code). `test_recheck.py`: 20 flagged pages, limit 4, highest 4. The recheck's page image is byte-identical to `render_page` at the policy's dpi. A rate-limit failure with a real provider was never reproduced. |
| 4 (queue cache) | fixed | `test_run_cache.py`; 0.35 s to 0.10 s on the demo project (see "After story 3"). |
| 6 (duplicate tests) | fixed | one `test_merge_checks.py` remains, under `tests/steps/`. |
| 7 (half-equal rule) | fixed | merge decisions identical (see "After story 6"); fixture files unchanged. |
| 9 (notebooks) | fixed | README passage; `tests/test_entrypoint.py::test_the_pdf_can_be_a_string_and_the_async_twin_works` already runs the async function inside a running loop. Not tried in a real notebook. |
| 11 (pandas and polars) | fixed | `tests/test_frames.py` (message) and the base-install check: in `uv run --no-dev --isolated`, `import quotable` works and neither library imports. `uv lock --check` is clean. |

Not run: a real Jupyter notebook; a request against a real provider; the review app in a browser.
