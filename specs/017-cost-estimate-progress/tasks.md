---

description: "Task list for spec 017: cost estimates, a cost limit and progress messages"
---

# Tasks: Cost estimates, a cost limit and progress messages

**Input**: Design documents from `specs/017-cost-estimate-progress/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/public-api.md, contracts/messages.md, quickstart.md (all present)

**Tests**: Required. The constitution (III) says new logic ships with offline tests, and money and a stop condition are in this feature. Write each story's tests first and watch them fail. Offline tests drive the pipeline with a fake client that reports a fixed cost per request. The one live test (T058) is opt-in and is not run without the user's go-ahead.

**Baseline (T001, 2026-11-12)**: `ruff`, `ty` pass; `just test` ran 2,874 passed in 62 s (`-n 4`). After the feature: 2,993 passed.

**Organization**: by user story. The stories are built in this order, which differs from the spec's numbering: US5 (the limit) first, because it needs only the meter and is the protection against a bill; then US1, US2, US3, US4, US6. Labels still use the spec's numbers.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: can run in parallel (different files, no dependency on an unfinished task)
- **[Story]**: US1 to US6 (the spec's user stories)
- Paths are from the repository root. Commit after each task or small group on `017-cost-estimate-progress` once the user approves; do not push.

---

## Phase 1: Setup

- [x] T001 Confirm the branch is `017-cost-estimate-progress`, run `just lint`, `just typecheck` and `just test`, and write the number of passing tests into the Baseline line of `specs/017-cost-estimate-progress/tasks.md`. Every later run must match it plus the new tests.

---

## Phase 2: Foundational (blocks every story)

**Purpose**: the error, money handling, the meter, the cost model, the client hooks, the printing core and the test doubles.

- [x] T002 [P] In `quotable/errors.py` add `CostLimitExceededError(BudgetExceededError)` with the fields of `contracts/public-api.md`: `reason` ("spent", "estimate", "unpriced", "unmetered"), `limit`, `spent`, `over`, `raise_by`, `estimate`, `finish_by`, `stage`, `done`, `total`, `in_flight` (all `Decimal` where money; `str(error)` is the full message). Export it from `quotable/__init__.py` (`__all__`, sorted as the file does). Test in `tests/test_errors.py` (create if absent): it is a `BudgetExceededError`, `str(error)` is the message, the fields are kept.
- [x] T003 [P] Create `quotable/meter.py` with the money helpers and their tests in `tests/test_meter.py`: `dollars(x)` ("2 decimals from $1 up, 4 decimals below $1"), `dollars_pair(a, b)` (enough decimals, up to 6, that the two strings differ), `round_up(x, places)` (never rounds down). Tests: `dollars_pair(Decimal("25.0412"), Decimal("25"))` shows both with the decimals needed; a total 0.000004 over the limit never prints equal; `round_up` of an exact amount returns it, of 0.04121 at 4 places returns 0.0413.
- [x] T004 Extend `quotable/meter.py` with `RunMeter` per `data-model.md`: fields `limit`, `total`, `phase`, `tallies` (`Tally`: requests, cache_hits, input_tokens, output_tokens, cost, unpriced), `in_flight`, `stopped`, `progress`, `sample_paid`, `sample_reused`, `started`. Methods `add(request, usage, cost)`, `begin()`, `end()`, `settled()`, `check()`, `paid(key, request)`, `hit(key, stage)`, `stage(name, total, upper_bound=False)`, `tick(name)`. Rules, quoted: "`stopped = "spent"` is set when `total > limit` (strictly)"; "A request whose price is unknown adds its tokens to the tally and nothing to `total`; with a limit set that request trips the meter first (`unmetered`)"; "Once `stopped` is set, `check()` raises on every later call". `check()` raises `CostLimitExceededError` built from the meter's current numbers (`spent`, `over`, `raise_by`, `stage`, `done`, `total`, `in_flight`). Tests in `tests/test_meter.py`: totals across phases and stages; equal to the limit does not stop, one cent over does; no usage with a limit stops as `unmetered`, without a limit does not; `settled()` waits for two in-flight requests; `check()` raises on every call after the stop; `raise_by` added to the limit is at least the total.
- [x] T005 [P] Add `CostModel` to `quotable/meter.py`: `name`, `price(input_tokens, output_tokens) -> Decimal | None`, `image_tokens(width_px, height_px, detail) -> int | None` and `why_unpriced`; `CostModel.for_model(model)` builds it with `infer_model` and prices through `ModelResponse(parts=[], usage=RequestUsage(...), model_name=..., provider_name=...).cost().total_price` (research 3.1). A `UserError` from `infer_model` and a `LookupError` or `AssertionError` from `.cost()` both mean "no price", with the cause kept in `why_unpriced`. Tests in `tests/test_meter.py` (set a dummy `OPENAI_API_KEY` with `monkeypatch`): `openai:gpt-4o` prices 10,000 input and 1,000 output tokens at 0.035; with the key unset the price is `None` and `why_unpriced` mentions the key; an unknown model name gives `None`.
- [x] T006 In `quotable/llm/client.py` give `CachedClient` the optional `meter` and `peek(request)` per plan.md ("The client"): `ask` calls `meter.check()` first, counts a cache hit (`meter.hit`), brackets the paid request with `begin()` / `end()` in a `finally`, stores the answer, calls `meter.paid(key, request)`, then `meter.check()`. Without a meter `ask` behaves exactly as today. Tests in `tests/llm/test_cached_client_meter.py`: the request keys with and without a meter are identical (pin three keys); after the meter trips no inner `ask` is called, cache hits included; the answer of the request that crossed the limit is in the cache and `check()` then raises; `max_requests` still raises `BudgetExceededError` first when both apply; `peek` returns the cached answer or `None`.
- [x] T007 [P] Create `quotable/progress.py` with the printing core: the sink protocol (`fixed(text)`, `live(text)`, `end_phase()`), `PlainSink` (stderr, lines only, no `\r` and no escape codes) and `NullSink`, and `Reporter(sink, meter)` with `fixed(text)` and `closing(error_or_none)`. The message builders for the closing messages live in `quotable/meter.py` as `limit_message(error) -> str` following `contracts/messages.md` section 5 for each `reason`. Tests in `tests/test_progress.py`: the plain sink writes whole lines to a captured stderr; `NullSink` writes nothing; `limit_message` for each of the four reasons contains the figures and the fixed phrases of the contract ("over by", "raise max_cost by at least", "Everything already answered is in the cache"); no message contains a prompt, a value or a path.
- [x] T008 [P] In `tests/conftest.py` add `PricedClient` (wraps a `FakeClient`, calls `meter.add(request, usage, cost)` with a fixed cost per request or a per-stage cost, and lets a test make a request report no usage) and a `fake_ipython` fixture (a stand-in `IPython` module in `sys.modules` with `get_ipython()`, `display` and `update_display` that record their calls). Used by T009 onward; a short test in `tests/test_meter.py` shows `PricedClient` adds to the meter.

**Checkpoint**: the pieces exist and are tested alone. Nothing is wired into `extract_tables` yet.

---

## Phase 3: User Story 5 - The limit stops the run the moment it is passed (Priority: P1) 🎯 MVP

**Goal**: with `max_cost` set, the run stops at once when its actual total passes the limit, and the error says what it cost and how much to raise the limit by.

**Independent Test**: a generated table with a priced fake model whose limit falls in the middle of extraction: the error is raised after the request that crossed it; no request starts after that; the figures agree with the cost log.

### Tests for User Story 5 (write first, watch them fail)

- [x] T009 [P] [US5] In `tests/test_cost_limit.py` write the scenarios of story 5 on a generated PDF (`make_pdf`) driven through `run_pipeline(..., costs=...)` with `PricedClient`: (1) the limit falls in the middle of extraction: the error is `reason == "spent"` and the count of requests started after the crossing is 0; (2) the figures: `spent` equals the sum of the fake costs, `over = spent - limit`, `limit + raise_by >= spent`; (3) four requests in flight when the limit is crossed: they finish and `spent` includes them, `in_flight == 4`; (4) a rerun with the limit raised by `raise_by` takes every answer already paid for from the cache and finishes; (5) a request that reports no usage with a limit set stops with `reason == "unmetered"` naming the stage; (6) no limit, no stop, even with the same costs; (7) the limit crossed by the very last request still raises and returns no tables; (8) `max_requests` and `max_cost` both set: the error that fires is the one whose number is reached first.
- [x] T010 [P] [US5] In `tests/test_entrypoint_cost.py` test the public function with a scripted model (`audit=False`): `max_cost=0` and `max_cost=-1` and `max_cost="abc"` raise `ValueError` before any request ("Must be greater than 0; anything else raises `ValueError` before any work"); `max_cost=0.1` is stored as `Decimal("0.1")`; the new arguments leave the request keys, the returned tables and the saved run identical to a call without them (FR-010).

### Implementation for User Story 5

- [x] T011 [US5] In `quotable/pipeline.py` add `CostContext` (`meter`, `reporter`, `cost_model`, `peek`; `None` means today's behavior exactly) and an optional `costs: CostContext | None = None` argument to `run_pipeline`. With a context, the phase is `"discovery"` until later stories change it. Nothing else in `run_pipeline` changes in this story.
- [x] T012 [US5] In `extract_tables_async` and `extract_tables` add `max_cost` and `progress` (signature of `contracts/public-api.md`): convert with `Decimal(str(value))`, validate, build the `RunMeter`, the sink (`NullSink` when `progress=False`, else `PlainSink` for now), the `Reporter` and the `CostModel`; chain `CostLog.record_usage` and `meter.add` as the `PydanticAIClient` `on_usage` callback; pass the meter to `CachedClient`; pass the `CostContext` to `run_pipeline`. Wrap the call as in plan.md ("Errors and the closing message"): on `CostLimitExceededError` with `reason == "spent"` or `"unmetered"`, `await meter.settled()`, rebuild the error with the settled numbers, print the closing message, raise. Update the docstring of `extract_tables_async` for both arguments. Make T009 and T010 pass.
- [x] T013 [US5] The closing message of any other failure (`ExtractionError`, `TextLayerError` and the rest): `Reporter.closing(None)` prints "stopped in the {stage} stage after ${spent}", then the error is raised unchanged. Test in `tests/test_cost_limit.py`: an `ExtractionError` still propagates, with the closing line printed once.

**Checkpoint**: `max_cost` works end to end with a plain, quiet display. US5 can be used on its own.

---

## Phase 4: User Story 1 - A cost estimate for discovery, before anything is sent (Priority: P1)

**Goal**: before the first request, a message gives the estimate and what it is based on; above the limit the run stops with nothing sent.

**Independent Test**: a generated PDF and a known price table: the message comes before the first request, the figure equals tokens times price, a limit just below it raises the error with no request made.

### Tests for User Story 1 (write first)

- [x] T014 [P] [US1] In `tests/test_estimate.py` pin the image rules to the providers' documentation examples (research 2): OpenAI `gpt-6-astra` at `detail="high"`: 1024 x 1024 gives 1,229 tokens, 2048 x 2048 gives 3,000, 4096 x 512 gives 2,458; `gpt-5.6-luna` at `original` keeps a 2550 x 3300 page at `ceil(80 x 104 x 1.2)`; a tile model (`gpt-4o`, `high`) gives base plus tiles; a model not in the table (and the deprecated `gpt-5-mini`) gives `None`; a dated name (`gpt-5.5-2026-01-01`) matches its family and `gpt-5.4-mini` does not match `gpt-5` by prefix; Anthropic 1000 x 1000 gives 1,296, 1920 x 1080 gives 2,691 and 3840 x 2160 gives 4,784 (high-resolution tier, always used); any other provider gives `None`.
- [x] T015 [P] [US1] In `tests/test_estimate.py` test `estimate_discovery` with a fake cost model (fixed tokens per image, price per token): requests = `ceil(pages / discovery_pages)`; input tokens = images + instructions + the known-tables allowance for windows after the first; output tokens = the per-page allowance times pages; cost = price of those; with the first two windows in the cache (written through a real `CachedClient`) the estimate covers only the rest and reports `cached == 2`; all windows cached gives cost 0 and `requests == 0`; image rule unknown gives `cost is None` and `unavailable` set; price unknown gives tokens and no dollars; the probe writes nothing to the cache.
- [x] T016 [P] [US1] In `tests/test_cost_limit.py` add the scenarios of story 1: the message appears before the first request and holds the page count, the request count, the figure and the basis; a limit below the estimate raises `reason == "estimate"` with `spent == 0` and no request made; no limit still prints and runs; scenario 5 (image rule unknown): the message says no estimate is available and the run continues with a limit set; scenario 6 (price unknown): no limit continues with token counts, a limit set raises `reason == "unpriced"` before any request, including before OCR and the text-layer check.

### Implementation for User Story 1

- [x] T017 [US1] Create `quotable/estimate.py` with `image_tokens(provider, model, width_px, height_px, detail)` and the rule tables from research 2 (OpenAI patch models with multiplier, budgets and maximum dimensions per detail; OpenAI tile models; Anthropic patches with the high-resolution cap, labelled "upper bound"), `text_tokens(text)` as `len(text) / 4` (with a `shortcut:` comment: a guess, replace with the provider's tokenizer if estimates prove low), and the constants `DISCOVERY_OUTPUT_PER_PAGE` and `KNOWN_TABLES_ALLOWANCE` (labelled guesses). A rule table carries the date it was read and a comment pointing at the documentation URL; the module docstring says new models need a row. Make T014 pass.
- [x] T018 [US1] In `quotable/estimate.py` add `Estimate` (fields of `data-model.md`), `CacheProbe` (an `LLMClient` that answers from `CachedClient.peek` and raises `NotCached` on a miss) and `estimate_discovery(page_sizes, images_policy, discovery_pages, extra_fields, cost_model, peek, pngs)`. Page sizes come from the page rectangles at 150 dpi and `detail="high"`, as discovery sends them; cached windows are found by running the real `discover` against the probe and counting the requests it answered. Make T015 pass.
- [x] T019 [US1] In `quotable/progress.py` add `Reporter.estimate(estimate, limit)` and the message builders for contract sections 1 (all three variants) and the "cost limit" line; in `quotable/meter.py` add the `reason == "estimate"` and `"unpriced"` texts to `limit_message`. Tests in `tests/test_progress.py` for each variant of the discovery estimate message.
- [x] T020 [US1] In `run_pipeline` (`quotable/pipeline.py`), after the text layer check, OCR and rendering and before `discover`: with a context, build the estimate, print it, and if the limit is set and `estimate.cost > limit` raise `CostLimitExceededError(reason="estimate")`. In `extract_tables_async`, before anything else: if a limit is set and the cost model has no price, raise `reason == "unpriced"`. Make T016 pass.

**Checkpoint**: US1 and US5 together give an estimate, a stop before spending and a stop during. 

---

## Phase 5: User Story 2 - Progress and running cost during discovery (Priority: P1)

**Goal**: while discovery runs, the display shows windows done of total and the cost so far.

**Independent Test**: discovery on 20 pages with a fake model; a plain stream has one line per milestone; the last state shows the total.

### Tests for User Story 2 (write first)

- [x] T021 [P] [US2] In `tests/test_progress.py` test `Reporter.stage_progress` with `PlainSink`: a stage prints a line at its start and one at its end, none in between; the line reads like the contract's "Live status line" (`discovery   12 of 75 windows   $0.84 so far (about $4.12)`); the estimate shows in parentheses only when it exists; a stage served entirely from the cache reads "(from the cache)" and adds no cost; a 100-page run prints at most 30 lines in total.
- [x] T022 [P] [US2] In `tests/test_cost_limit.py` add: a discovery of 20 pages with a priced fake model leaves a last state of "5 of 5 windows" and a cost equal to the sum of the fake costs; windows answered from the cache are counted as done with no cost.

### Implementation for User Story 2

- [x] T023 [US2] In `quotable/progress.py` add `Reporter.stage_progress()` (reads `meter.progress` and `meter.total`), the status-line builder and the throttle (at most 4 redraws a second, always one when a stage ends; the clock is a parameter so tests do not sleep). In `RunMeter.tick` call a listener the reporter registers. In `run_pipeline` set `meter.stage("schema", windows)` before `discover`; `CachedClient` ticks the stage after each answered request (paid or cached). Make T021 and T022 pass.

**Checkpoint**: US2 works with the plain sink. Terminal and notebook forms come in Phase 8.

---

## Phase 6: User Story 3 - A sample run, then a better estimate for extraction (Priority: P1)

**Goal**: after discovery, the full process runs on 3 table pages, and a new estimate for the rest is printed and checked against the limit.

**Independent Test**: a generated 30-page table with a priced fake model: after the sample the estimate for the rest equals the measured cost per page times the pages left (plus the not-reused term), and a limit between the sample's cost and the expected total stops the run after the sample.

### Tests for User Story 3 (write first)

- [x] T024 [P] [US3] In `tests/test_sample.py` test `choose_sample(jobs)`: "positions `round(i * (T - 1) / 2)` for i in 0, 1, 2" over the jobs in (table, page) order; 4 jobs give three distinct pages; 3 or fewer jobs give none; the choice is the same on every call; with two tables the sample can hold pages of both; a shared page counts once for each table on it.
- [x] T025 [P] [US3] In `tests/test_cost_limit.py` add the regression that guards the refactor: for a generated multi-page, two-table PDF with a scripted model, `run_pipeline` with and without a cost context returns identical tables (rows, groundings, positions, audit, proposals, merged), and the requests of the full run are the same set as before the change (same keys). Add the sample scenarios: the sample announcement lists the pages; the extraction requests of the sample are cache hits in the rest (counted by the client); the audit and recheck requests of the sample that differ are paid again and appear in "could not be reused"; a limit between the sample's cost and the expected total raises `reason == "estimate"` after the sample with no further extraction request; a document of 3 table pages prints the "small enough" line and has no sample phase; a page shared by two tables is grounded against the same band in the sample and in the rest.
- [x] T026 [P] [US3] In `tests/test_estimate.py` test `estimate_rest` with tallies from a fake sample: `per_page`, the rest term `(T - N) * c + N * (c - e)`, `expected_total = spent + rest`, `possibly_low` set when any sample request was a cache hit, a sample of cached answers gives 0 and `possibly_low`.

### Implementation for User Story 3

- [x] T027 [US3] In `quotable/pipeline.py` move the code of `run_pipeline` after discovery into an inner function `process(jobs, ...)` over a set of (table index, page) jobs: bands (`table_page_layers`) and layouts (`page_layouts`) are computed once from the full discovery before it and filtered to the jobs' pages; extraction, grounding, audit, extra fields (restricted to the jobs' pages), merge and recheck as today. Without a cost context `run_pipeline` calls `process` once with all jobs and returns exactly what it returned before. Make the first half of T025 (the regression) pass before anything else in this phase changes.
- [x] T028 [US3] Add `choose_sample(jobs)` (module `quotable/pipeline.py`) and the sample phase to `run_pipeline`: with a context and more than 3 jobs, set `meter.phase = "sample"`, announce, call `process(sample_jobs)` with merge skipped, discard its tables, then `meter.phase = "rest"` and call `process(all_jobs)`. Make T024 pass.
- [x] T029 [US3] In `quotable/estimate.py` add `estimate_rest(meter, total_jobs, sample_jobs)` per plan.md ("The estimates") and `Estimate.per_page`, `expected_total`, `possibly_low`. In `quotable/meter.py` implement `sample_paid` / `sample_reused` / "not reused" (`paid` stores the cost of a paid sample request under its cache key; `hit` adds that cost to `sample_reused` the first time the key is asked for again in the rest phase). Make T026 pass.
- [x] T030 [US3] In `quotable/progress.py` add `Reporter.announce_sample(...)` (contract section 2, both variants) and `Reporter.estimate_rest(...)` (section 3, with the "note" line for `possibly_low`). In `run_pipeline`, after the sample: print the estimate and, if the limit is set and `expected_total > limit`, raise `CostLimitExceededError(reason="estimate")` before the rest starts; add the `"estimate"` text for the after-sample case to `limit_message`. Make the rest of T025 pass.

**Checkpoint**: the run goes through discovery, sample and rest, and the limit is checked after each estimate.

---

## Phase 7: User Story 4 - Progress and cost while extracting, and a final summary (Priority: P1)

**Goal**: the sample and the rest show their stage, progress and cost, and one final message sums the run up.

**Independent Test**: a whole pipeline with a priced fake model: one final message, its total equals the sum of the cost records of the run, its counts equal the saved run's.

### Tests for User Story 4 (write first)

- [x] T031 [P] [US4] In `tests/test_progress.py` test the stage lines for extraction ("96 of 177 pages"), audit and recheck ("12 of up to 177"), the sample ("6 of 9 requests"), each with the cost so far and, for the rest, the estimated cost of the rest in parentheses.
- [x] T032 [P] [US4] In `tests/test_cost_limit.py` add the final-message scenarios: exactly one final message; its total equals the sum of `.quotable/cost/requests.jsonl` for the run to the cent (run with a real `CostLog` in the test's temporary working directory); new requests per stage and cache hits match the meter; the pages, tables and table pages match the returned tables; "could not be reused" equals the sample's paid cost minus what the rest asked for again; a model with no price prints token counts and "no price known"; a run with no limit leaves out the limit part; elapsed time is printed.

### Implementation for User Story 4

- [x] T033 [US4] In `run_pipeline` set `meter.stage(...)` for `extract` (exact total: the jobs), `audit` and `recheck` (total: the table pages, `upper_bound=True`) and `extras` when extra fields are on, for the sample and for the rest. Make T031 pass.
- [x] T034 [US4] Add `Reporter.final(tables, meter, estimates, pages)` (contract section 4) and call it at the end of `extract_tables_async`; the estimates and the pdf page count are passed from `run_pipeline` through the `CostContext`. Make T032 pass.

**Checkpoint**: a whole run prints the estimate, the sample, the progress and the summary with the plain sink.

---

## Phase 8: User Story 6 - Output that fits where it is shown (Priority: P2)

**Goal**: the same content shows as one updating block per phase in a notebook, one rewritten line in a terminal, and plain lines in a file; `progress=False` prints nothing.

**Independent Test**: the same run to a captured file, to a fake terminal and to a fake notebook: no control codes in the file, one rewritten line in the terminal, 4 display ids in the notebook.

### Tests for User Story 6 (write first)

- [x] T035 [P] [US6] In `tests/test_progress.py` test `TerminalSink` with a fake tty stream: the live line is rewritten with a carriage return and a clear-line code, cleared before a fixed message is printed, and the stream ends without a dangling live line.
- [x] T036 [P] [US6] In `tests/test_progress.py` test `NotebookSink` with `fake_ipython`: each phase creates one display (`display_id`), every later redraw is an `update_display` of the same id, the block text holds the phase's fixed lines followed by the live line, a run leaves exactly 4 displays (discovery, sample, rest, final) and a 100-page run at most 5 blocks (SC-004), two runs at the same time keep separate ids.
- [x] T037 [P] [US6] In `tests/test_progress.py` test `choose_sink`: a plain stream gives `PlainSink`; `sys.stderr.isatty()` true gives `TerminalSink`; `IPython` loaded with a `ZMQInteractiveShell` gives `NotebookSink`; `IPython` not in `sys.modules` is never imported; `progress=False` gives `NullSink`; a sink that raises on `fixed` or `live` is replaced by `PlainSink`, the run continues and nothing fails (FR-020); the output of a file run contains no `\r` and no `\x1b`.
- [x] T038 [P] [US6] In `tests/test_cost_limit.py` add the end-to-end checks: with `progress=False` nothing is written to stdout, stderr or the fake notebook and the limit still stops the run (FR-019); standard output stays empty in every other mode (the messages go to stderr or the cell output).

### Implementation for User Story 6

- [x] T039 [US6] In `quotable/progress.py` add `TerminalSink` and `NotebookSink` (`display({"text/plain": text}, raw=True, display_id=...)` then `update_display`, per research 1) and `choose_sink(progress)` with the notebook test of research 3.11; wrap every sink call in the `Reporter` so a failure replaces the sink with `PlainSink` once and the run goes on. Make T035 to T038 pass.
- [x] T040 [US6] In `extract_tables_async` use `choose_sink` in place of the temporary `PlainSink` of T012.

**Checkpoint**: all six stories work. 

---

## Phase 9: Polish & cross-cutting concerns

- [x] T041 [P] README: a new "Cost limit and progress" section (the two arguments, the messages in a terminal and a notebook, what the estimates are and are not, that `max_cost` can be passed by the cost of the requests in flight, that a stopped run is cached so a rerun is cheap, and that notebook display is checked only in the frontends named in the spec); edit the "Cost" section so `cost-report` is described as after the fact and the new messages as during; remove "a dollar cap" from "Not carried over yet" and from the "Not handled" list; keep the human voice, no changes to unrelated sections.
- [x] T042 [P] `AGENTS.md`: add spec 017 to the project state paragraph (what is implemented, what was not checked: JupyterLab, VS Code, Colab and the live estimate accuracy), add `meter.py`, `estimate.py`, `progress.py` and the new test files to the file structure, update the `errors.py` line (now five exceptions) and the `llm/client.py` line, and the next free spec number (018). Constitution: "`AGENTS.md` MUST be updated in the same change".
- [x] T043 [P] Update `specs/017-cost-estimate-progress/spec.md` status from Draft to Implemented once the tasks are done, and tick `checklists/requirements.md` if anything changed.
- [x] T044 Run `just hooks`, `just typecheck` and `just test`; all must pass and the test count must equal the Baseline plus the new tests. Fix findings; do not bypass hooks.
- [x] T045 Walk through `quickstart.md`'s offline section and tick each line; the notebook and live part is the user's, with their go-ahead.
- [x] T046 [P] Opt-in live test `tests/live/test_live_cost_estimate.py` (marked `live`, skipped unless `OPENAI_API_KEY` and `QUOTABLE_LIVE_TEST_MODEL` are set, `max_cost` set low): runs a small real PDF, records the discovery estimate, the rest estimate and the actual cost side by side, asserts only that a limit below the discovery estimate stops before any request and that the final total equals `cost-report`. It prints the estimate error for SC-003. **Do not run it without the user's explicit go-ahead.**

---

## Dependencies & Execution Order

### Phase dependencies

- **Setup (1)**: no dependencies.
- **Foundational (2)**: after Setup; blocks everything. T002, T003, T005, T007 and T008 are parallel; T004 follows T003; T006 follows T004.
- **US5 (3)**: after Phase 2. Tests T009, T010 in parallel, then T011 to T013 in order. This is the MVP.
- **US1 (4)**: after Phase 3 (it needs the entry point wiring of T012). T014 to T016 in parallel; T017, T018, T019, T020 in order.
- **US2 (5)**: after Phase 4 (it uses the same reporter and the stage calls in `run_pipeline`).
- **US3 (6)**: after Phase 5. T027 first and alone (the refactor), with its regression test green before T028 to T030.
- **US4 (7)**: after Phase 6.
- **US6 (8)**: its sinks can be built any time after Phase 2 (T035 to T037 and the sink classes of T039 touch only `progress.py`); T040 wires them and needs T012.
- **Polish (9)**: after the stories wanted.

### Within each story

Tests are written first and must fail. Then the module work, then the wiring in `pipeline.py`. `pipeline.py` and `progress.py` are shared files, so tasks that edit them are not marked [P].

### Parallel opportunities

- Phase 2: T002, T003, T005, T007, T008.
- Phase 4 tests: T014, T015, T016. Phase 6 tests: T024, T025, T026. Phase 8 tests: T035 to T038, and `TerminalSink` / `NotebookSink` (T039) can be built while Phase 6 is under way.
- Polish: T041, T042, T043, T046.

### Parallel example: User Story 1 tests

```bash
Task: "Pin the image rules to the documentation examples in tests/test_estimate.py"        # T014
Task: "Test estimate_discovery with a fake cost model in tests/test_estimate.py"           # T015
Task: "Add the story 1 scenarios to tests/test_cost_limit.py"                              # T016
```

## Implementation Strategy

### MVP first

1. Phase 1 and Phase 2.
2. Phase 3 (US5): `max_cost` stops a run at once with a useful error, with quiet or plain output.
3. **Stop and validate**: T009 and T010 pass; the cost-log total equals the error's total.
4. Then Phase 4 (the estimate before spending) and Phase 5 to Phase 8 in order.

### Incremental delivery

Each phase leaves a runnable library: after Phase 3 there is a hard limit; after Phase 4 an estimate and an early stop; after Phase 6 the sample; after Phase 7 the summary; after Phase 8 the notebook form.

## Notes

- The risky step is T027, moving the post-discovery code into `process`. The regression test (identical tables and identical request keys with and without a cost context) comes first and must stay green.
- The image rule tables (T017) are the part that goes stale. Each row has the documentation URL and the date read, and a model not in the table says so instead of guessing.
- `progress=False` is an addition the user did not ask for (plan.md, Complexity Tracking); the user may remove it.
- Verify tests fail before implementing. Commit after each task or logical group once the user approves the tasks.
