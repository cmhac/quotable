# Research: A table that fails validation no longer stops the run

Spec: [spec.md](spec.md). Plan: [plan.md](plan.md). Each entry is a decision, why, and what else was considered. What was read in the code or measured is said as such; what is a judgement is said as such.

## 1. Where a failed table is recorded

**Decision**: a list `Table.problems: list[Problem]`, and `Table.failed` is `bool(problems)`. A `Problem` is `(stage, pages, message)` with `stage` one of `"discovery"`, `"extraction"`, `"location"`.

**Why**: FR-002 asks for every problem, with its pages and stage, on the table. A failed table is an ordinary `Table`, so everything that already handles a `Table` (saving a run, the closing message, the frames) keeps working with an empty `columns`, `pages` and so on.

**Alternatives**: a `FailedTable` subclass (every `isinstance` and every `replace` would need care; the spec asks the user to tell tables apart "by its flag"); a single `error: str` (cannot hold several problems or their pages).

## 2. Window-level and table-level problems in discovery

**Decision**: `answer_problems` (built in PR #5) returns two kinds. Window-level problems (wrong page count, wrong extra-field names) keep raising `ExtractionError` after the one retry, as before ("Not changed"). Table-level problems (no columns, a blank name, a repeated name) are checked per table and, after the retry, mark that table failed. The second answer is used as it is: its valid tables are kept, its unusable ones fail.

**Why**: the spec says a window answer that is wrong after its retry still raises, and that only the unusable table fails. The retry is the whole window because that is what the page-count retry already does.

**Read in the code**: `discover.py` today validates at the end (`validate_found`) and raises on the first bad table. `merge()` groups by `signature(columns)`, so every empty-columns table has the same signature; that is how 16 pages of three tables became one table (finding 5).

**Failed entries**: grouped by label (FR-006): a failed `Found` is keyed by `("failed", label)`, which cannot equal a sound table's signature. Its `rows` holds the pages. If a window reports the same label twice on a page, the existing `Found.add` rule applies.

## 3. Which tables the model is shown in later windows

**Decision (clarification 2)**: `known_tables()` skips failed tables. In the Trump run two of the four empty answers (pages 421-424 and 545-548) were copies of the first: the empty table sat in the known list and the model reproduced it. Verified by replaying the cache: the known-tables text of those two requests listed "table 8: pages [357, 358, 359, 360]; columns: []".

**Consequence**: the pages of a failed table that later windows meet again are judged on their own, and can form a sound table. A table with the same label may then exist twice (one failed, one sound); that is correct and the user sees both.

## 4. The warning category

**Decision**: `class TableFailedWarning(UserWarning)` in `quotable/errors.py`, exported from `quotable`. One category for the warning at failure and the warning on reads, so one filter controls both. Messages: [contracts/messages.md](contracts/messages.md).

**Why**: Principle II says failures are typed in `quotable.errors`. A `UserWarning` subclass is the ordinary way to let a user silence, show or escalate (Story 2, scenario 4). `RuntimeWarning` suggests a numerical problem and `DeprecationWarning` is hidden by default.

## 5. One warning per accessor call

**Read in the code**: `records()` calls `rows()`; `to_pandas()` and `to_polars()` call `records()`; `flagged()` calls `rows()`; `rows()` calls `page_rows()`. Warning in each would give three warnings for one `to_pandas()`.

**Decision**: each public accessor warns once and then calls a quiet private twin (`_rows`, `_page_rows`, `_records`, `_flagged`). Package code that must read a failed table without warning (the saved-run writer in `runs.py`) calls the private twins. `stacklevel` points at the user's line.

**Python's own de-duplication**: with the default filter a warning is shown once per place and text, so a loop over `records()` shows one line. `warnings.simplefilter("always")` shows every call. FR-004 is about what the library emits; the filter decides what is shown.

## 6. When the failure warning is emitted

**Decision**: once per table, at the end of the stage in which it failed, and only in the full pass, never in the sample pass of spec 017. A sample failure is thrown away with the sample and would repeat in the full pass, which would warn twice for one failure.

- Discovery failures: right after discovery returns.
- Location failures: right after the bands are computed (before extraction).
- Extraction failures: at the end of the extraction stage; one warning lists every page of that table that failed.

A table fails at most once in this sense: stages after the first failure skip it.

**Judgement**: "at the moment a table fails" is read as "when its stage finds the problem", not as "inside the failing request". The difference is seconds to minutes, and it lets one warning carry all of a table's problems.

## 7. Location and extraction failures

**Read in the code**: `layout.table_layers` raises `ExtractionError` for a first or last row not found, a last row above the first, and overlapping bands; `extract_page` raises `ExtractionError` after its retry.

**Decision**: `layout.py` raises `BandError(ExtractionError)` with `labels` (the tables at fault; both for an overlap). `table_page_layers` catches it per page, records a `location` problem on each named table, and recomputes the page's bands for the tables that remain. `one()` in the pipeline catches the `ExtractionError` of `extract_page` for its own (table, page) and records an `extraction` problem. Only `ExtractionError` is caught: `BudgetExceededError` and its subclass `CostLimitExceededError` are different classes and still stop the run.

**To check in the tests**: a survivor alone on a page that another table also uses must still get a band from its own rows, not the whole page layer. `table_layers` takes a list of specs, so one spec should work; a test pins it.

## 8. Later stages and failed tables

**Decision**: failed tables are not given to `merge_tables`, `recheck_table` or `audit_table`, and are left out of `all_jobs`, the layouts, the extra-field scope (`Discovery` for `resolve_extra_fields`) and the estimates. They are put back in the returned list at the end. No stage needs to know about them except as "not mine".

**Order of the returned list**: unchanged for a call with no failed table (no sorting is done). With failed tables, the list is ordered by each table's first page, stable for ties, so a failed table sits where it first appeared. This is the "order of first appearance" assumption of the spec.

**Estimates**: the discovery estimate is unchanged. The estimate for the rest counts only jobs of sound tables, so it is smaller when tables fail. That is correct.

## 9. OCR: flow, the dependency and the platforms

**Flow** (in `usable_layers`):

1. Pages with no words are the empty pages. If there are any and an engine exists, OCR exactly those, replace their layers, and continue with the merged layers.
2. Run the existing check. A document with no words at all, or too many garbled pages, is handled as today (garbled pages are OCR'd then; an empty page OCR already did is a cache read).
3. With `ocr=False`: the existing "no text layer on any page" rejection is kept as it is. Otherwise, if more than `MAX_GARBLED_PAGE_SHARE` (10%) of the pages are empty, raise `TextLayerError` naming how many pages have no text, with `REMEDY_OCR_OFF`. At most 10% is accepted as today.
4. `Table.ocr_pages` and the saved run list the OCR'd pages as today.

The 10% value is the existing constant, reused, as the spec says. It is not tuned on data.

**Facts read on PyPI (2026-11-13)**: `paddlepaddle` 3.3.1 has wheels for `macosx_11_0_arm64`, `manylinux1_x86_64` and `win_amd64`, for CPython 3.9 to 3.13 only: none for Intel Macs, Linux ARM or Python 3.14. `paddleocr` 3.7.0 is one pure-Python wheel (`py3-none-any`) that requires `paddlex[ocr-core]`; it does not require `paddlepaddle`.

**Decision**: both packages go into `dependencies`, each with the same marker, so they install only where PaddlePaddle can run:

```text
python_version < '3.14' and ((sys_platform == 'darwin' and platform_machine == 'arm64')
    or (sys_platform == 'linux' and platform_machine == 'x86_64')
    or (sys_platform == 'win32' and platform_machine == 'AMD64'))
```

Elsewhere neither is installed, and a document that needs OCR raises `OcrUnavailableError` before any request (the import-failure path in `paddle.py`, whose text changes).

**Judgement, to verify in the first task**: that `uv lock` resolves with these markers, and that `pip install` on an unsupported platform succeeds. The markers are standard environment markers, so both should hold; neither has been run.

**The extras**: `ocr` and `ocr-core` are removed, not kept as aliases. Nothing in the repo needs them, `pip` only warns when an extra is missing, and the project is at 0.1.0. The dev group stops listing the two packages. The messages and tests that name `quotable[ocr]` and `quotable[ocr-core]` change (`paddle.py`, `tests/ocr/test_ocr_device.py`, `tests/ocr/test_paddle_adapter.py`, `tests/test_ocr_pipeline.py`, the README).

**NVIDIA users**: install quotable (CPU PaddlePaddle comes with it), then `pip uninstall paddlepaddle` and install `paddlepaddle-gpu`. The README's GPU section says so. Still untested on real hardware.

**Size and CI**: everyone on a supported platform downloads about 100 to 200 MB more (PaddlePaddle wheel sizes: 104 MB on macOS and Windows, 194 MB on Linux) plus PaddleX's own dependencies, which were not measured. The CI job on Linux will install them on every run unless the uv cache keeps them; not measured. The offline tests still use the fake engine and never import PaddleOCR.

## 10. The cache entry format

**Read in the code**: `CachedClient.ask` writes `answer.model_dump_json(indent=1)` and reads with `request.output_type.model_validate(json.loads(...))`. No answer model sets `extra="forbid"` (searched `model_config` and `extra=` in the package: none), so pydantic ignores keys it does not know.

**Decision**: the details go in one extra top-level key, `_quotable`, beside the answer's own fields. Old code reading a new entry ignores it; new code reading an old entry finds none. The two are told apart by the key's presence, and no entry is rewritten. The entry is written with `json.dumps(..., indent=1, ensure_ascii=False)` of `answer.model_dump(mode="json")` plus the key. Contents: [contracts/stored-files.md](contracts/stored-files.md).

**Why not a wrapper object** (`{"answer": ..., "details": ...}`): old entries would then differ in shape from new ones, every reader would need two paths, and an older quotable would fail to read a new entry instead of ignoring it.

**To check**: no test reads the text of a cache file (a search of `tests/` found only tests that list file names or compare keys: `tests/test_cache.py`, `tests/llm/test_llm.py`, `tests/llm/test_cached_client_meter.py`); the first task of Story 6 re-checks that before changing the writer. `tests/llm/test_llm.py` pins that `request_key` is unchanged.

## 11. Linking a retry to its original

**Decision**: `Request` gets `pages`, `retry_of` and `problem`, none part of the key (like `stage` and `page`). `_ask_window` and `extract_page` build the retry with `retry_of=request_key(client.identity, first_request)` and `problem` set to the problems joined. `CachedClient` writes them. For stages other than discovery, `pages` falls back to `(request.page,)`.

**To check in the tests**: that the recheck, audit and extra-field requests all set `page`; any that do not get `pages` set in the same change.

## 12. What changes for pages that used to be empty (spec asked the plan to check)

**Read in the code**: `recheck._request` sends `"\n".join(table.layers[page].lines())`, which is an empty string for an empty layer, and flags every cell of such a page (`ungrounded`), so the recheck asked about them with no text. `audit.unexplained` finds words in the layer that no cell explains; with an empty layer it finds none, so the audit never asked about an empty page.

**Consequence**: once a page has OCR text, its recheck request differs (it now carries the text), and the audit may now ask about it (up to one request per OCR'd page, a new cost). This is the carve-out already in FR-012; the spec text says "differ", and this adds that audit requests can newly exist. The README's note on cost changes accordingly.

## 13. Spec 018 (one concurrency limit)

Both specs touch `steps/discover.py` and the request gate in `pipeline.py`. 019 keeps its discovery changes to `answer_problems`, `Found`, `merge`, `known_tables`, `validate_found` and the retry request's fields, and does not move the `client.ask` calls or the gate. Whichever lands second resolves the conflict in `_ask_window`; it should be small.

## 14. Progress messages for OCR

**Read in the code**: `Reporter` has `fixed(text)` for lines that stay and a status line driven by the meter, which counts model requests and money. OCR is neither.

**Decision**: OCR of more than 5 pages reports with `fixed` lines: one at the start ("OCR of N pages without text, M of them already in the cache"), then one at each 10% done, then one at the end with the time. `ocr_pages` gets an optional `on_page(done, total)` callback; the pipeline passes a function that marshals the call to the event loop with `call_soon_threadsafe`, because `ocr_pages` runs in a worker thread and a notebook display must not be written from one. With `progress=False` nothing is printed.

**Judgement**: 5 is "a handful"; it is a constant (`OCR_PROGRESS_FROM`), not an option.

## 15. The closing message (FR-010)

**Decision**: `Reporter.final` adds one line when at least one table failed, naming them: `  N tables failed: <label> (pages ...), ...` after the summary line. A call with none prints exactly what it printed. The summary line's table count stays `len(tables)`, which now includes failed tables; the new line says how many of them failed.

## 16. The saved run and the review app (FR-011)

**Decision**: `tables.json` and `run.json` gain `failed` and `problems` per table and a `failed` count in the summary; `load_run` reads runs without them as not failed. `FORMAT_VERSION` stays 1, as spec 014 did for its new keys. The review app is not given a new screen. Task: build the demo project with one failed table, open its run and table screens in the browse API tests, and fix what raises on an empty `columns` or `pages`. How richly a failed table is shown stays undecided, as the spec says.

**Judgement**: the writer must not warn, so it uses the quiet accessors.

## 17. Principle II and the unapproved amendment

The plan finds the amendment unnecessary (see the Constitution Check). If the user still wants the wording changed, it is a separate `speckit-constitution` run and does not block any task here.

## 18. Tests and checks

- **Red then green**: each behavior starts with a failing offline test (scripted client, a generated PDF where possible). The replay (SC-001) uses `tests/data/discovery_empty_columns/answer_*.json`, the model's recorded answers; the retry's answer is made up in the test and the test says so.
- **SC-003 enforced**: `filterwarnings = ["error::quotable.errors.TableFailedWarning", ...]` in `pyproject.toml`; tests that expect the warning use `pytest.warns`.
- **SC-004 (live)**: run `tests/live/test_live_discovery_columns.py` only with the user's go-ahead. It passed 6 of 6 on the old code, so it cannot show the fix; it shows that the four windows end as a table or a failed table, never as an error, which needs the failure to occur. Treat SC-004 as met only if a failing answer is seen or the user accepts the recorded replay as the check.
- **Not checkable offline**: the real OCR of the 901 Trump pages (time unmeasured), the install on each platform, and the notebook display. These stay in "not checked" in AGENTS.md until done.
