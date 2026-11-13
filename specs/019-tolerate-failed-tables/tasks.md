---
description: "Task list for spec 019: a table that fails validation no longer stops the run"
---

# Tasks: A table that fails validation no longer stops the run

**Input**: Design documents from `specs/019-tolerate-failed-tables/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/public-api.md, contracts/messages.md, contracts/stored-files.md, quickstart.md (all present)

**Tests**: Required (FR-018, Constitution III). Each story starts with its tests; write them, run them, watch them fail for the stated reason, then implement. The real model is never replaced by a scripted one to test model behavior: the scripted clients here test the library's reaction to an answer, and the replay uses the model's own recorded answers.

**Baseline (T001, 2026-11-13)**: `ruff` and `ty` pass; `just test -n 4` ran 2,996 passed in 86 s (2,993 before PR #5, plus 3 new tests). After T014 (the MVP): 3,036 passed. After T019: 3,050 passed. After T030: 3,072 passed; after T038: 3,074 passed (2,996 before, plus 78 new tests; `ruff`, `ty` and `just hooks` pass).

**Already built (PR #5, branch commit `e4d49f9`)**: `answer_problems` in `quotable/steps/discover.py` makes a window answer invalid when a table has no columns, a blank name or a repeated name, and the window is asked once more. Its test `test_an_answer_with_no_columns_that_persists_raises` in `tests/steps/test_discover.py` describes the old end (a raise); T008 and T009 change it.

**Organization**: by user story, in dependency order rather than the spec's numbering. US2 (reading warns) comes first because it needs only a hand-built `Table`. US3 (discovery) then US1 (the whole call) are the fix for the reported run. US4 (later-stage failures), US6 (cache entries) and US5 (OCR) follow; US6 and US5 do not depend on US1 to US4 and may be built in either order or by someone else in parallel.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: can run in parallel (different files, no dependency on an unfinished task)
- **[Story]**: US1 to US6, the spec's user stories
- Paths are from the repository root. Commit after each task or small group on `019-tolerate-failed-tables` once the user approves; do not push without being asked.
- Every task ends with `just lint`, `just typecheck` and the tests it touches passing; the full `just test` runs at the end of each phase.

---

## Phase 1: Setup

- [x] T001 Confirm the branch is `019-tolerate-failed-tables`, run `just lint`, `just typecheck` and `just test -n 4`, and write the number of passing tests into the Baseline line of `specs/019-tolerate-failed-tables/tasks.md`.

---

## Phase 2: Foundational (blocks every story)

**Purpose**: the public types and the test doubles every story uses.

- [x] T002 [P] In `quotable/errors.py` add `class TableFailedWarning(UserWarning)` with a one-line docstring, export it from `quotable/__init__.py` (`__all__`, alphabetical like the others), and add to `tests/test_errors.py` a test that it is a `UserWarning` subclass, is in `quotable.__all__`, and is importable as `from quotable import TableFailedWarning`.
- [x] T003 [P] In `quotable/table.py` add `Problem`, a frozen dataclass: `stage: Literal["discovery", "extraction", "location"]`, `pages: tuple[int, ...]` (never empty: raise `ValueError` in `__post_init__` if it is), `message: str`. Add to `Table`, as the last dataclass field so every existing construction still works, `problems: list[Problem] = field(default_factory=list)`, and the property `failed -> bool` returning `bool(self.problems)`. Export `Problem` from `quotable/__init__.py`. Tests in a new `tests/test_table_failed.py`: a `Table` built the old way is not failed; with a problem it is; `Problem(stage="discovery", pages=(), message="x")` raises `ValueError`; `Problem` is frozen; `Problem` is in `quotable.__all__`. (Depends on nothing; T002 and T003 touch different files except `quotable/__init__.py`, so make that one edit together.)
- [x] T004 In `pyproject.toml` add `"error::quotable.errors.TableFailedWarning"` to `filterwarnings` (keep the existing entry), so that any `TableFailedWarning` a test does not expect fails the test (SC-003). Run `just test -n 4`: still all passing. (Depends on T002.)
- [x] T005 [P] In `tests/table_builder.py` add `failed_table(label="t", problems=None, pages=None)` that returns a `Table` with the given `Problem`s (default: one `discovery` problem on page 1 with the message "no columns") and, when `pages` is given, the rows of those pages built the way the module's other helpers build a sound table. Used by T006 and T017. (Depends on T003.)

**Checkpoint**: `TableFailedWarning`, `Problem` and `Table.failed` exist and the suite is green.

---

## Phase 3: User Story 2 - Reading a failed table warns instead of raising (Priority: P1)

**Goal**: every way of reading a failed table's data returns what it holds and warns once per call.

**Independent Test**: [quickstart.md](quickstart.md) section 1, `tests/test_table_warnings.py`.

- [x] T006 [US2] Write `tests/test_table_warnings.py` first, with `warnings.simplefilter("always")` in each test that counts warnings. For a failed table from `failed_table` (T005) with extracted pages, and one with none: each of `rows()`, `page_rows(1)`, `records()`, `to_pandas()`, `to_polars()` and `flagged()` returns without raising and records exactly one `TableFailedWarning` whose text matches `contracts/messages.md` section 2 (the table's label, the problem, the accessor's name, "may be incomplete or wrong"); `to_pandas()` and `to_polars()` record one warning, not three; reading `label`, `columns`, `pages`, `problems` and `failed` records none; a sound table records none from any accessor; an empty failed table gives `[]` from `rows()`, `records()` and `flagged()` and a frame with zero rows and the usual columns from `to_pandas()` and `to_polars()`; `page_rows(99)` on a failed table raises `KeyError` as on a sound one; with `warnings.simplefilter("error", TableFailedWarning)` reading a failed table raises `TableFailedWarning`. Run them and watch them fail because nothing warns.
- [x] T007 [US2] In `quotable/table.py` give `Table` the quiet private twins `_page_rows`, `_rows`, `_records` and `_flagged` holding today's bodies (the inner calls use the twins, never the public names). Each public accessor calls one `_warn_if_failed(name)` and then its twin. `_warn_if_failed` does nothing for a sound table; otherwise `warnings.warn(msg, TableFailedWarning, stacklevel=3)` with the text of `contracts/messages.md` section 2 (`table '<label>'`, `'unnamed'` for an empty label; the problems' messages joined with `; `). `to_pandas` and `to_polars` call `self._records()` and `_frame_columns()`; a missing pandas or polars still raises `ImportError` unchanged. Make T006 pass and run `just test -n 4`.

**Checkpoint**: a hand-built failed table can be read, with one warning per call.

---

## Phase 4: User Story 3 - A table with no columns is not accepted from the model (Priority: P1)

**Goal**: an unusable table in a window answer is retried once, and if it is still unusable only that table fails; failed tables are never shown to later windows.

**Independent Test**: `tests/steps/test_discover.py` and the replay of the four recorded windows.

- [x] T008 [US3] Copy the two remaining cached bad answers of the failed run into `tests/data/discovery_empty_columns/` as `answer_421_424.json` (from `3ca1d2eafc6cbcd9db070ebd8e2c1ad95cb1cd972ffc0cceb5a41799733715f6.json`) and `answer_545_548.json` (from `58614099bf7e1d0b8e634ef9285f27c4b6b2039811bd8a33682744bf1747a690.json`), both in `/Users/hackerc/projects/2026-11-12-senate-expenditures/data/intermediate/quotable_cache/`. Then write the new tests in `tests/steps/test_discover.py` first and watch them fail: (a) a window whose second answer still has one unusable table and one valid table returns both, the valid one sound and the other failed with its problem text, after exactly 2 requests, and does not raise; (b) a page-count problem that persists still raises `ExtractionError` "still invalid", and so does a window that has both a page-count problem and an unusable table; (c) failed entries are grouped by label: the same label on two pages is one failed table, two labels are two, and a failed table is never grouped with a sound one (signature `("failed", label)`); (d) blank and repeated column names fail like no columns; (e) a window after a failed one is sent without that table in `known_tables()`, and when no sound table exists yet it is sent without `CARRY_PROMPT` and without a "Known tables" part (clarification 2); (f) the replay: four windows of four pages each, each answered with a recorded file (`answer_357_360`, `answer_421_424`, `answer_545_548`, `answer_889_892`) twice, return 4 failed tables with the right pages, no raise, 8 requests (FR-018, SC-001; the test says in a comment that the answers are the model's recorded ones and nothing is sent to a model). Change `test_unusable_discovery_results_raise` so `validate_found([])` still raises "no table" and the per-table columns cases move to (a) and (d), and change `test_an_answer_with_no_columns_that_persists_raises` to expect a failed table.
- [x] T009 [US3] In `quotable/steps/discover.py`: add `problems: list[str]` and the property `failed` to `Found`; make `merge()` classify each reported table with the existing `validate_schema` (catch its `ExtractionError`), and for an unusable one use the key `("failed", label)` instead of `signature(...)`, keeping the model's columns as given; `known_tables()` skips failed entries; `_ask_window` adds `CARRY_PROMPT` and the known-tables part only when at least one sound table exists, and after the retry raises only for window-level problems (page count, extra-field names), leaving table-level ones to `merge()`; `validate_found` raises only when `found` is empty. Keep the `client.ask` calls and their order as they are (spec 018 changes the same function). Make T008 pass, then run `just test -n 4`.

**Checkpoint**: discovery returns failed tables instead of raising, and the model is never shown one.

---

## Phase 5: User Story 1 - One bad table does not cost me the others (Priority: P1) 🎯 MVP

**Goal**: `extract_tables` returns the sound tables and the failed ones, warns once per failed table, names them in the closing message and saves them in the run.

**Independent Test**: `tests/test_failed_tables.py`; [quickstart.md](quickstart.md) section 1.

- [x] T010 [US1] Write `tests/test_failed_tables.py` first (builders from `tests/conftest.py`: `make_pdf`, `FakeClient`, `replay`, `window_of`, `one_table`; see `tests/test_tables.py` for a three-table document), and watch it fail: (a) a document of 3 tables on separate pages where the scripted model gives `columns: []` twice for the second returns 3 tables in page order, the second failed with one `discovery` problem naming its pages, exactly one `TableFailedWarning` recorded (`pytest.warns` with the count checked), no raise, and no extraction request for its page; (b) SC-002: the other two tables' `records()` equal those of the same call on a PDF without the failing table; (c) every table failing returns the failed tables and does not raise; (d) FR-012: for a document with no failure, the requests recorded by the client (prompts and `request_key`s) equal those recorded before this change (pin them from a run on the unchanged code before T011) and no warning is emitted; (e) the call finishes when the failed table's pages are also the pages of a sound table (a page two tables share). Use `with warnings.catch_warnings(record=True)` and `simplefilter("always")` for every count.
- [x] T011 [US1] In `quotable/pipeline.py`: after `discover(...)`, split `discovery.tables` into sound and failed; build each failed one as `Table(columns=<the model's columns>, pages=[], layers={}, grounded={}, position={}, label=<label>, problems=[Problem("discovery", tuple(pages), <message>)])`; warn once per failed table right after discovery with the text of `contracts/messages.md` section 1; use only the sound `Found`s for `table_page_layers`, `layouts`, `all_jobs`, the sample and the extra-field scope (`Discovery(...)` handed to `resolve_extra_fields`); at the end, when and only when there are failed tables, insert them into the returned list ordered by first page (stable for ties, `min(problem pages)` for a failed table). A call without a failed table must take the same path as before (no sort). Make T010 pass and run `just test -n 4`.
- [x] T012 [P] [US1] Closing message (FR-010). In `tests/test_progress.py` first: with one or more failed tables `Reporter.final(...)` adds, after the summary line, `  N tables failed: '<label>' (pages <ranges>), ...` exactly as in `contracts/messages.md` section 3 (1 table: `1 table failed: ...`); with none the output equals today's text. Then add it to `Reporter.final` in `quotable/progress.py`. Page ranges are written like `357-360` and `3, 5-6`.
- [x] T013 [US1] Saved run (FR-011). Tests first in `tests/test_runs.py` and `tests/test_save_runs.py`: a run saved from a failed table and a sound one writes `failed` and `problems` for the failed one and a `failed` count in the summary, and `load_run` reads them back; a run written before this change (no keys) loads as not failed; saving a failed table emits no `TableFailedWarning`; a failed table with no pages and `columns: []` saves without error. Then in `tests/review/test_browse_api.py` and `tests/review/test_review_demo.py`: the runs list, the run screen's API and the table's rows API answer without error for a run that holds a failed table, and the demo project shows it. See `contracts/stored-files.md` section 2.
- [x] T014 [US1] Implement T013: in `quotable/runs.py` write `failed` and `problems` per table and `failed` in the summary, read them with defaults (`RunTable.failed = False`, `problems = []`; `FORMAT_VERSION` stays 1), and make the writer use `table._rows()` instead of `table.rows()` (it must not warn); in `tests/review_demo.py` add one run that has a failed table (offline, fake models) and update `tests/review/test_review_demo.py`'s expectations; fix whatever in `quotable/review/browse.py` raises on a table with no columns or no pages. Run `just test -n 4`.

**Checkpoint**: the reported failure is fixed end to end: the Trump-style run returns tables, with the bad ones marked.

---

## Phase 6: User Story 4 - Later-stage failures of one table are tolerated too (Priority: P2)

**Goal**: rows still invalid after the retry, a row not found on a shared page and overlapping bands fail only the tables concerned; later stages skip failed tables.

**Independent Test**: `tests/steps/test_layout.py` and `tests/test_failed_tables.py`.

- [x] T015 [US4] Tests first in `tests/steps/test_layout.py` (watch them fail): `table_layers` raises `BandError` (a subclass of `ExtractionError`, so every existing `pytest.raises(ExtractionError)` still passes) with `labels` naming the table whose first or last row was not found (one label), the table whose last row is above its first (one label), and both tables of an overlap, and with the `page`; the messages are unchanged.
- [x] T016 [US4] In `quotable/steps/layout.py` add `class BandError(ExtractionError)` with `page: int` and `labels: tuple[str, ...]` and raise it in the three places that raise `ExtractionError` today. Make T015 pass.
- [x] T017 [US4] Tests first in `tests/test_failed_tables.py` (watch them fail): (a) rows invalid twice for one page of one table: the table is failed with an `extraction` problem naming that page, keeps the rows of its other pages (a page before and one after the bad page), the other tables are sound, one warning; (b) a table whose rows are invalid on every page is failed with no pages; (c) two tables whose bands overlap on a page are both failed with `location` problems that name the other, a third table elsewhere is sound; (d) a table whose first row is not found on a shared page fails alone, and the other table on that page still gets its band from its own first and last rows (research 7); (e) the sample: with a document of more than 3 table pages and the cost context of `tests/conftest.py`'s `PricedClient`, an extraction failure on a sampled page produces one warning for the whole call, not two; (f) `BudgetExceededError` and `CostLimitExceededError` raised inside extraction still stop the run and are not turned into problems; (g) `merge_tables` never merges a failed table into another or another into it, even when the failed table's columns equal a sound table's; (h) a recording client sees no recheck, audit or extra-field request for a failed table's pages, and none of those stages raises.
- [x] T018 [US4] In `quotable/pipeline.py`: `table_page_layers` catches `BandError` per page, records a `location` problem on each named table, and recomputes that page's bands for the tables that remain (a lone survivor gets `table_layers(page, layer, [its spec])`); `one()` catches the `ExtractionError` of `extract_page` for its own (table, page) and records an `extraction` problem (messages as in the existing text); when a table's pages are assembled, a table with problems becomes a `Table` with the pages that did extract and its problems, even when none did; warn once per newly failed table at the end of the location step and of the extraction stage, only in the full pass (`only is None`), never in the sample pass; failed tables are left out of the later stages and put back by the T011 ordering. Make T017 (a) to (f) pass.
- [x] T019 [P] [US4] Make T017 (g) and (h) pass: `merge_tables` in `quotable/steps/merge.py` partitions failed tables out and puts them back in place; `recheck_table` in `quotable/steps/recheck.py` and `audit_table` in `quotable/steps/audit.py` return a failed table unchanged before doing anything; the extra-field scope in `quotable/pipeline.py` already excludes them from T011 (check, no new work). Run `just test -n 4`.

**Checkpoint**: no check that concerns one table raises any more; document-level failures still raise (pinned by T008 (b), T017 (f) and the existing tests).

---

## Phase 7: User Story 6 - A cache entry says what it is (Priority: P2)

**Goal**: new cache entries record stage, pages, model, time, run id and, for a retry, what it retried and why. Independent of US1 to US4 except for the retry's problem text (T009).

**Independent Test**: `tests/llm/test_cache_entries.py`; [quickstart.md](quickstart.md) section 3.

- [x] T020 [US6] First re-check that no test reads the text of a cache file (`tests/test_cache.py`, `tests/llm/test_llm.py` and `tests/llm/test_cached_client_meter.py` only list names or compare keys). Then write `tests/llm/test_cache_entries.py` (watch it fail): an entry written through `CachedClient(..., run_id="r" * 32)` holds the answer's own fields unchanged plus `_quotable` with `stage`, `pages`, `model` (the client's `identity`), `written` (matches `YYYY-MM-DDTHH:MM:SSZ`) and `run`; a discovery request for pages 357-360 records `[357, 358, 359, 360]`; a request that sets only `page` records `[page]`; a client built without a run id writes `run: null`; the retry made by `_ask_window` and the one made by `extract_page` record `retry_of` equal to `request_key(identity, first_request)` and a `problem` naming the problem; the first request's own entry has neither key; an entry without `_quotable` (written by hand in the old format) is read and used and its file is byte-identical afterwards; `output_type.model_validate` on a new entry gives the same answer as before; no entry contains a prompt text, image bytes, a file path or the string "sk-"; `request_key` of a request is the same with and without the new fields set (`pages`, `retry_of`, `problem`); with the stages' fakes, every cache file written by a small pipeline run with one unusable answer has the details and the retry names its original.
- [x] T021 [US6] In `quotable/llm/client.py` add the optional `pages: tuple[int, ...] = ()`, `retry_of: str | None = None` and `problem: str | None = None` to `Request` after `page` (not part of `request_key`), `run_id: str | None = None` to `CachedClient.__init__`, and make `CachedClient.ask` write `json.dumps({**answer.model_dump(mode="json"), "_quotable": {...}}, indent=1, ensure_ascii=False)` with exactly the keys of `contracts/stored-files.md` section 1 (`retry_of` and `problem` only for a retry; `pages` falls back to `(request.page,)`). If building the details fails, write the entry without them. In `quotable/steps/discover.py` set `pages=tuple(pages)` on the window request and `retry_of=request_key(client.identity, first)` and `problem="; ".join(problems)` on the retry; in `quotable/steps/extract.py` set `retry_of` and `problem` on its retry; check that the recheck, audit and extra-field requests set `page` (or `pages`) and add it where one does not; pass `run_id=cost_log.run_id` where `extract_tables_async` builds the client. Do not move the `client.ask` calls. Make T020 pass, then run `just test -n 4` (the pinned keys in `tests/test_cache.py` and `tests/llm/test_llm.py` must pass unchanged).

**Checkpoint**: a cache entry can be read without the pipeline; old entries still work.

---

## Phase 8: User Story 5 - Every page without text is OCR'd, and OCR comes with quotable (Priority: P2)

**Goal**: every empty page is OCR'd before any model request; PaddleOCR installs with quotable where PaddlePaddle has a wheel.

**Independent Test**: `tests/ocr/test_empty_pages.py` with the fake engine; `just test-ocr` for the real one; [quickstart.md](quickstart.md) section 2.

- [x] T022 [US5] Tests first, watch them fail. In `tests/text/test_textcheck.py`: the new empty-page rule (more than `MAX_GARBLED_PAGE_SHARE`, 10%, of the pages have no words) is true for 3 of 20 and false for 2 of 20 and for exactly 10%. In a new `tests/ocr/test_empty_pages.py` (fake engine from `tests/fake_ocr.py`, PDFs from the `make_pdf` fixture): a 20-page PDF with text on 2 pages: the engine is asked for exactly the other 18 pages (and for none of the 2), before any model request, and `Table.ocr_pages` lists them; a page where the engine finds nothing stays empty with no error; if no page has any word after OCR, `TextLayerError` as today; `ocr=False` and 3 of 20 pages empty raises `TextLayerError` before any request (`calls.count == 0`) with the text of `contracts/messages.md` section 6 (naming 3 of 20), 2 of 20 is accepted as today, a PDF with no text anywhere keeps today's "no text layer" message; a second call finds the OCR'd pages in the cache and the engine is asked for none; garbled-page behavior is unchanged (the existing tests in `tests/test_ocr_pipeline.py` pass unchanged); with progress on, OCR of 6 or more pages prints the start line, a line per 10% and the end line of `contracts/messages.md` section 5 as plain lines, and of 5 or fewer prints none, and `progress=False` prints none.
- [x] T023 [US5] In `quotable/text/quality.py` add the empty-page share check and its message, and in `usable_layers` in `quotable/pipeline.py` implement the flow of research 9: find the pages with no words; with an engine OCR exactly those, merge the layers and carry on with the existing check (garbled pages are OCR'd only when the document is still rejected; a page OCR'd already is a cache read); with `ocr=False` keep today's "no text layer" rejection and otherwise reject above the 10% share before any request. `ocr_pages` in `quotable/ocr/pages.py` gets an optional `on_page(done, total)` callback; the pipeline passes a function that reaches `Reporter` through `loop.call_soon_threadsafe`; add `Reporter.ocr_start`, `ocr_progress` and `ocr_done` to `quotable/progress.py` (constant `OCR_PROGRESS_FROM = 5`). `Table.ocr_pages` keeps listing the OCR'd pages of the table. Make T022 pass, then run `just test -n 4`.
- [x] T024 [US5] Dependencies. In `pyproject.toml` move `paddleocr==3.7.0` and `paddlepaddle==3.3.1` into `dependencies`, each with the marker `python_version < '3.14' and ((sys_platform == 'darwin' and platform_machine == 'arm64') or (sys_platform == 'linux' and platform_machine == 'x86_64') or (sys_platform == 'win32' and platform_machine == 'AMD64'))`; remove the extras `ocr` and `ocr-core` and the two packages from the `dev` dependency group; run `uv lock` and `uv sync`; check in `uv.lock` that both packages appear only under that marker; run `just test -n 4` (the offline suite must still pass with the fake engine and without importing PaddleOCR) and `uv run python -c "import quotable; import sys; assert 'paddleocr' not in sys.modules"`. Say in the task note what was and was not checked: the lock and the install on this machine only; other platforms and Python 3.14 stay unchecked. (Depends on nothing; do before T025.)
- [x] T025 [US5] Messages and docs. Update the tests that name the extras first (`tests/ocr/test_paddle_adapter.py` lines about `quotable[ocr]`, `tests/ocr/test_ocr_device.py` lines about `quotable[ocr-core]`, `tests/test_ocr_pipeline.py`) to the texts of `contracts/messages.md` section 6, watch them fail, then change `INSTALL`, the no-wheel note and the GPU texts in `quotable/ocr/paddle.py`. In `README.md` rewrite "Installing OCR" (OCR comes with `pip install quotable` on macOS arm64, Linux x86_64 and Windows x86_64 with Python 3.11 to 3.13; elsewhere `OcrUnavailableError`) and "OCR on an NVIDIA GPU" (install quotable, then `pip uninstall paddlepaddle` and install `paddlepaddle-gpu`; still untested on hardware), add the install size (about 100 to 200 MB, not measured beyond the PaddlePaddle wheel) and that the audit can now ask about OCR'd pages (research 12); update `tests/data/README.md` if its GPU checklist names the extras.
- [x] T026 [P] [US5] (run 2026-11-13: passed, 79 s for one page including the model load; found QUALCOMM, AMGEN and AFLAC) Add to `tests/ocr/test_real_ocr.py` (opt-in, `-m ocr`) a test that OCRs page 1 of `tests/data/discovery_empty_columns/pages_357_360.pdf` (a scanned page of the Trump report) with the real engine and finds words from its first rows (`QUALCOMM`, `AFLAC`, `AMGEN`) in the layer. It costs time and downloads about 140 MB of models on first use, never a model request; run it with `just test-ocr` only with the user's agreement. Write the time it takes in the task note.

**Checkpoint**: a scanned document is OCR'd page by page before any request, and the dependency is in place.

---

## Phase 9: Polish and cross-cutting

- [x] T027 [P] In `README.md` add a short section on failed tables (what `extract_tables` returns, `table.failed`, `table.problems`, the warning and how to turn it into an error or silence it, what still raises) and update "Not handled" and "Not carried over yet" if they mention the old raising behavior.
- [x] T028 [P] Update `AGENTS.md`: Project state (spec 019 implemented, what was and was not checked, the OCR default dependency and the removed extras, 1.1.0), the file structure lines for `errors.py`, `table.py`, `pipeline.py`, `progress.py`, `runs.py`, `llm/client.py`, `steps/discover.py`, `steps/layout.py`, `text/quality.py`, `ocr/` and the new tests, and every mention of `quotable[ocr]` or `quotable[ocr-core]`. The test count comes from T030.
- [x] T029 [P] Update the `Status` line of `specs/019-tolerate-failed-tables/spec.md` from "Draft, partly built" to what is true after this work, listing the unchecked items (real OCR time of 901 pages, installs on other platforms, the notebook display, SC-004 unless T031 was run).
- [x] T030 Run `just lint`, `just typecheck`, `just test -n 4` and `just hooks`; check SC-006: list the existing tests that were changed and confirm each expected an error from a check that now fails a table; write the final test count into `AGENTS.md` and this file's Baseline line. Run `speckit-converge` and append anything it finds.
- [ ] T031 (not run: needs the user's go-ahead) SC-004, only with the user's explicit go-ahead (Constitution III): run `just test-live tests/live/test_live_discovery_columns.py` and report the answer plainly: the empty answers are rare (6 of 6 windows were fine on the old code), so a pass does not show the fix; the replay in T008 does.

---

## Dependencies and order

```text
T001 → T002, T003 (together) → T004, T005
T005 → T006 → T007                         (US2)
T007 → T008 → T009                          (US3; needs no US2 code, but the warning type)
T009 → T010 → T011 → T012, T013 → T014      (US1; T012 and T013 are parallel)
T014 → T015 → T016 → T017 → T018 → T019     (US4)
T009 → T020 → T021                          (US6; independent of US1, US2 and US4 otherwise)
T001 → T022 → T023, T024 → T025, T026       (US5; independent of everything above)
all → T027, T028, T029 → T030 → T031
```

## Parallel opportunities

- T002 and T003 (different files; share the one `__init__.py` edit), T005 after T003.
- T012 (`progress.py`) with T013 (`runs.py` tests), both after T011.
- T019 (`merge.py`, `recheck.py`, `audit.py`) with T018 once T017's tests exist.
- The whole of US6 (T020, T021) and the whole of US5 (T022 to T026) can run beside US1 to US4 by someone else, if they avoid `quotable/steps/discover.py` and `quotable/pipeline.py` at the same time as T009, T011 and T018; T021 and T023 touch those files and should go after the P1 phases.
- T027, T028 and T029.

## Implementation strategy

**MVP: Phases 1 to 5 (T001 to T014).** That is the reported failure fixed: US2, US3 and US1, all P1. After T014 a run like the Trump report returns its tables, marks the bad ones, warns, and saves them. Stop and show it before going on.

Then US4 (T015 to T019) so that no check about one table can still end a run; then US6 and US5 in either order (US5 needs the user's agreement to run the real OCR and changes what everyone installs, so it is last in the default order). Each story leaves the suite green, so the branch can be merged after any phase if the user wants to ship in parts.

## Notes

- Constraints quoted from `data-model.md`: `Problem.stage` is one of `"discovery"`, `"extraction"`, `"location"`; `Problem.pages` is a `tuple[int, ...]`, never empty; `Table.problems` is the last field; the signature of a failed `Found` is `("failed", label)`; `Request.pages`, `retry_of` and `problem` are not part of the key; `FORMAT_VERSION` stays 1.
- Nothing is pushed by these tasks. PR #5 already carries the first commit of this spec.

- **T030, SC-006**: the existing tests that were changed, each for a stated reason: `tests/steps/test_discover.py` (a check on one table no longer raises), `tests/test_extract.py` and `tests/test_tables.py` (rows still invalid, and a band that cannot be isolated, now fail that table), `tests/test_cost_limit.py` ("another failure" is a `RuntimeError`, because an `ExtractionError` from extraction is now a problem), `tests/test_entrypoint.py` and `tests/test_merged_field.py` (they pin the public names and the `Table` fields), `tests/ocr/test_ocr_device.py`, `tests/ocr/test_paddle_adapter.py` and `tests/test_ocr_pipeline.py` (the install texts no longer name the extras), `tests/review_demo.py` and `tests/review/test_review_demo.py` (the demo has a failed table). `speckit-converge` has not been run.

---

## Phase 10: Convergence

**Purpose**: what `speckit-converge` found on 2026-11-13 between the spec, plan and tasks and the code. Findings: F1 FR-009 partial (HIGH), F2 research 12 partial (MEDIUM), F3 stored-files contract partial (LOW), F4 stored-files contract partial (LOW), F5 quickstart partial (LOW), F6 unrequested (LOW), F7 results not recorded (LOW). T031 (the live check) is unchanged: it needs the user's go-ahead.

- [x] T032 Make the extra-field stage skip a table that failed in extraction, per FR-009 (partial). Test first in `tests/test_failed_tables.py` (`ExtraFields` through `run_pipeline`, as `test_extra_fields_ignore_a_table_that_failed_in_discovery` does): a table whose page 2 fails extraction and whose pages 1 and 3 extract has no `extra_fields` and no `extra_names`, no extra-field request names a page only that table is on, and a sound table on other pages still gets its fields. Then in `quotable/pipeline.py` build the scope of `extras_stage` from the tables that are neither located-failed nor extraction-failed (pass the failed indices from `process` to `extras_stage`), and make `attach_extra_fields` return a failed table unchanged (today a location-failed table gets `extra_names` and an empty `extra_fields`).
- [x] T033 In `README.md`, under "The text layer, and OCR", say that a page that is now OCR'd can get an audit request where an empty page never did, so a run with many OCR'd pages can cost more (up to one request per OCR'd page), per research 12 and T025 (partial).
- [x] T034 Add to `tests/llm/test_cache_entries.py` a test that an entry is still written, without `_quotable`, when its details cannot be built (a `Request` whose `pages` is not iterable), per `contracts/stored-files.md` section 1 (partial).
- [x] T035 Describe `failed`, `problems` and the summary's `failed` in the module docstring of `quotable/runs.py`, where the run format is documented, per `contracts/stored-files.md` section 2 (partial).
- [x] T036 In `specs/019-tolerate-failed-tables/quickstart.md` replace the reference to `tests/test_replay_failed_run.py`, which does not exist, with `tests/steps/test_discover.py` (the replay of the four recorded windows is `test_the_four_recorded_windows_of_the_failed_run_end_as_four_failed_tables`) per SC-001 (partial).
- [x] T037 Mark `Table.first_page`, `Table.problem_pages`, `Table.warn_failure` and `page_ranges` in `quotable/table.py` as internal in their docstrings, and say in `contracts/public-api.md` that they are not part of the public API, since the contract lists only `problems`, `failed` and the six data accessors as additions (unrequested).
- [x] T038 Record what was run on 2026-11-13 in `tasks.md` (T026's note), `AGENTS.md` ("Not checked") and the Status line of `spec.md`: the real OCR test of one scanned report page passed in 79 s including the model load and found QUALCOMM, AMGEN and AFLAC, so 901 pages are hours, not minutes (not measured beyond one page); and `extract_tables(<the Trump report>, ocr=False)` raises `TextLayerError` naming "no text on 901 of 927 pages" before any request (SC-005, second half) (partial).

- **T032, what was done**: the finding was narrowed. The extra-field requests are made per page and a page that only a failed table is on may print a header that carries forward to a sound table, so those pages are still read (a `shortcut:` comment on `attach_extra_fields` says so). What the stage no longer does is give a failed table extra fields (`extra_names`, `extra_fields`). **Open**: T031 (the live check), which needs the user's go-ahead.
