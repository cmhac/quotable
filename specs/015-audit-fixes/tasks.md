# Tasks: Audit fixes

**Input**: [spec.md](spec.md), [plan.md](plan.md), [research.md](research.md), [quickstart.md](quickstart.md), [contracts/install-and-errors.md](contracts/install-and-errors.md)

**Tests**: required by the constitution (principle III) for every piece of new logic. Each story writes its tests first and runs them on the unchanged code to see them fail, then makes them pass.

**Format**: `- [ ] T### [P] [US#] description with file path`. `[P]` means it touches a different file from the other open tasks of its phase and depends on none of them.

**Before you start**: you are on branch `spec/015-audit-fixes`. Never use `--no-verify`. Stage files by name. Commit at each story checkpoint. Nothing is pushed. No live or OCR test is run.

## Phase 1: Setup (baselines, before any code changes)

- [X] T001 [P] Record the queue baseline. Build the demo project with `uv run python -m tests.review_demo build/review-demo`, run the timing script from the Story 3 section of `specs/015-audit-fixes/quickstart.md` three times, and write the three numbers under a new `## Results` heading at the end of `specs/015-audit-fixes/spec.md` (heading "Baseline on main, 2026-11-10": spec says about 0.40 s).
- [X] T002 [P] Record the merge baseline. Run `uv run python -m tests.score_merge --detail > $KIROCREW_SCRATCH/score_merge_before.txt` and copy the line for the default rules (the first variant) into `## Results` in `specs/015-audit-fixes/spec.md`. Also run `git status --short tests/data/synthetic` and confirm it prints nothing.

## Phase 2: Foundational

None. The stories are independent; each can be done and committed alone.

## Phase 3: User Story 1 - The recheck stays within the request limit (P1) 🎯 MVP

**Goal**: no more than 4 model requests in flight in a run, rechecks included (FR-001 to FR-003).

**Independent test**: a 20-page table with a flagged cell on every page, rechecked through a shared semaphore of 4 against a client that counts overlapping `ask` calls, never shows more than 4.

- [X] T003 [US1] Create `tests/test_recheck_limit.py` with a pipeline-level test. Use the sample `tests/data/fy22_ag_house_original.pdf` (4 pages) and its `.rows.json` as `tests/steps/test_recheck.py` does (`replay`, `FakeClient`), put a one-word typo in one cell on every page, and wrap the client so `ask` counts overlapping calls (increment, `await asyncio.sleep(0.01)`, decrement, keep the maximum). `monkeypatch.setattr("quotable.pipeline.MAX_CONCURRENT_REQUESTS", 1)`, run `run_pipeline(PDF, client, audit=True)` through `asyncio.run`, and assert the maximum overlap is 1 and that at least 2 requests had stage `"recheck"` (so the test cannot pass without a recheck). Run it now: it MUST fail on the unchanged code (the recheck is not limited). Note the failure in your report.
- [X] T004 [P] [US1] In `tests/steps/test_recheck.py` add two tests of `recheck_table` with the new signature `recheck_table(table, pdf, client, images, gate)`. (a) Build a 20-page table with `tests.table_builder.build_table(tmp_path, ...)`, replace one cell on every page with a misspelled value and re-ground with `quotable.table.ground_document` so each page has a `fuzzy` cell, call it with `asyncio.Semaphore(4)` and the overlap-counting client from T003, and assert the maximum overlap is 4 or less and that 20 recheck requests were made. (b) For one page, assert the `Image` part of the recheck request equals `quotable.steps.extract.render_page(pdf, page, images.dpi)` (FR-003: same image bytes as before). These will fail with `TypeError` until T006.
- [X] T005 [P] [US1] In `tests/steps/test_extra_fields_recheck.py` add a test of `recheck_fields` with the new signature (`..., client, gate`): fuzzy or ungrounded values on 10 pages, an `asyncio.Semaphore(4)`, the `Asker` class already there with an overlap counter added; assert the maximum overlap is 4 or less. Update that file's `run` helper to pass a semaphore.
- [X] T006 [US1] Edit `quotable/steps/recheck.py`. Give `recheck_table` and `recheck_fields` a required last parameter `gate: asyncio.Semaphore`. In `recheck_table`, replace the up-front `pymupdf.open` and `render_png` loop with a small inner coroutine that does `async with gate:` then `png = render_page(pdf, n, images.dpi)` then `await client.ask(_request(table, n, png, images.detail))`, and `asyncio.gather` that coroutine over `pages`. In `recheck_fields`, wrap each `client.ask(request(p))` in `async with gate:`. Remove the `pymupdf` and `render_png` imports if nothing else uses them; import `render_page` from `quotable.steps.extract`. Update the module docstring's "Deliberately left out" paragraph only if it becomes untrue.
- [X] T007 [US1] Edit `quotable/pipeline.py`. Add a `gate: asyncio.Semaphore` parameter to `resolve_extra_fields`, delete its own `asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)` line and use the parameter in `look` and in the `recheck_fields` call. In `run_pipeline`, pass the existing `gate` to `resolve_extra_fields(...)` and to every `recheck_table(t, pdf, client, images, gate)`. Update the stage description in the module docstring only if it says anything about the limit.
- [X] T008 [US1] Update the remaining callers: `tests/test_extra_fields_output.py` (the `recheck_table(table, tmp_path / "t.pdf", client)` call, add `TODAY` from `quotable.llm.images` and `asyncio.Semaphore(4)`), and `tests/live/test_live_audit.py` (the `recheck_table(audited, PDF, client, images)` call, pass the same semaphore style it uses for `audit_table`). Do not run the live test.
- [X] T009 [US1] Run `uv run pytest tests/test_recheck_limit.py tests/steps tests/test_extra_fields_output.py tests/test_entrypoint.py -q`; all must pass, including the T003 test that failed before. Then `uv run ruff check quotable tests` and `uv run ty check`. **Checkpoint**: stage the files you changed by name and commit as "Spec 015 story 1: the recheck follows the request limit".

## Phase 4: User Story 2 - The review app renders page images one at a time (P1)

**Goal**: at most one PyMuPDF render at a time in the review app (FR-004 to FR-006).

**Independent test**: 20 concurrent page-image requests return valid images and never overlap in the render step.

- [ ] T010 [US2] Create `tests/review/test_render_lock.py`, using the `app` fixture (imported by `tests/review/conftest.py`) and `sources.clear_caches()` as `tests/review/test_browse_api.py` does around line 1370. (a) Patch `quotable.steps.extract.render_png` with a wrapper that counts overlapping calls (increment, `time.sleep(0.02)`, call the real one, decrement, keep the maximum); start 20 threads that each `app.get(f"{app.run('senate')}/pages/{n}.png")` for `n` in 1 and 2, join them, and assert every status is 200, every body starts with the PNG signature, and the maximum overlap is 1. (b) Patch the wrapper to raise `RuntimeError` on its first call only; assert that request answers an error status (the app answers "the PDF cannot be read") and the next request for the same page answers 200. Run it now: (a) MUST fail on the unchanged code (overlap greater than 1).
- [ ] T011 [US2] Edit `quotable/review/sources.py`: add `_render_lock = threading.Lock()` next to `_lock`, and hold it around the `with pymupdf.open(path) ...: png = render_png(...)` block in `page_png` (keep the existing `except (OSError, ValueError, RuntimeError)` outside or around it so the lock is released on failure). Add one line to the module docstring saying renders are serialized because PyMuPDF is not thread-safe.
- [ ] T012 [US2] Run `uv run pytest tests/review -q`, `uv run ruff check quotable tests`, `uv run ty check`. **Checkpoint**: commit as "Spec 015 story 2: the review app renders one page at a time".

## Phase 5: User Story 3 - The review queue stays quick as documents pile up (P2)

**Goal**: repeated queue and verdict requests read no run file when nothing changed, and build the item list once (FR-007 to FR-009a).

**Independent test**: on a project of 10 distinct documents, the second `get_queue` reads 0 run files; a changed file is read again.

- [ ] T013 [US3] Create `tests/review/test_run_cache.py`. Copy `built.project` to a temp `.quotable` (as the `app` fixture does) and add enough copied run folders to reach 10 distinct documents: copy a run folder to a new 32-hex-digit name and set `id` and `sha256` to new values in its `run.json` (see `edit_run` in `tests/review/test_browse_api.py`); assert the number of distinct `sha256` values is at least 10 so the test cannot pass vacuously. Tests: (a) patch `quotable.review.sources.load_run` with a counting wrapper, call `get_queue(Request(project, (), {}, None))` twice, and assert the second call made 0 reads; (b) change one run's `tables.json` (size changes) and assert exactly that run is read on the next call and the answer reflects it; (c) set `sources._RUN_BYTES` to a small number with `monkeypatch`, load three runs, and assert the least recently used is dropped and a run larger than the budget is still kept when it is the only one; (d) patch `quotable.review.queue.scoped_items` with a counting wrapper and assert one `get_queue` calls it once. Run it now: all four MUST fail on the unchanged code. (a) fails because only 4 runs are cached, so the second call reads the other 6 again; (b) fails for the same reason (more than one run is read); (c) and (d) fail because `_RUN_BYTES` and `scoped_items` do not exist yet.
- [ ] T014 [P] [US3] Edit `quotable/review/sources.py`: replace `_RUNS = 4` with `_RUN_BYTES = 64 * 1024 * 1024`; store each cache entry's file size (the sum of the two `st_size` values already read for the stamp) and, after inserting, evict from the least recently used end while the total size is over `_RUN_BYTES` and more than one entry remains. Update the module docstring line about the cached runs.
- [ ] T015 [P] [US3] Edit `quotable/review/queue.py`: rename `_scoped_items` to `scoped_items` (search the whole repo for other uses first: `grep -rn "_scoped_items" quotable tests`) and keep `population` and `counts_by_status` calling it with unchanged signatures and results.
- [ ] T016 [US3] Edit `get_queue` in `quotable/review/review.py` (depends on T015): call `scoped_items(runs, settings)` once, take `pop = [i for i in items if i.status in settings.statuses]`, and `counts = dict(Counter(i.status for i in items))` in place of the two calls, keeping the result keys and their order as they are (compare with `counts_by_status`). Leave `_find`, `_next` and the `population` import for them.
- [ ] T017 [US3] Run `uv run pytest tests/review -q` (the existing queue and API tests must pass unchanged), then repeat the timing script from T001 three times and add the numbers to `## Results` in `specs/015-audit-fixes/spec.md` as "After story 3". SC-003 needs at most half of the baseline. If it is not reached, record what else is slow (profile with `cProfile` as in `research.md`) and report it instead of declaring success. Also record the memory budget as measured: file size and parsed size of the 3,024-row run, if you re-measure. **Checkpoint**: commit as "Spec 015 story 3: the review queue keeps runs by size and builds items once".

## Phase 6: User Story 4 - Install without the two DataFrame libraries (P2)

**Goal**: pandas and polars are optional extras, and a missing one gives a clear `ImportError` (FR-010 to FR-013).

**Independent test**: with `sys.modules["pandas"] = None`, `to_pandas()` raises `ImportError` naming `quotable[pandas]`; a base environment has neither library.

- [ ] T018 [US4] In `tests/test_frames.py` add two tests: with `monkeypatch.setitem(sys.modules, "pandas", None)`, `table.to_pandas()` raises `ImportError` whose message contains `to_pandas() needs pandas` and `pip install "quotable[pandas]"`, and `records()` still works; the same for polars. Use whichever table helper the file already uses. Run them: they MUST fail on the unchanged code (the message is different).
- [ ] T019 [US4] Edit `quotable/table.py`: wrap `import pandas as pd` in `to_pandas` and `import polars as pl` in `to_polars` in `try/except ImportError as err`, raising `ImportError` with the exact text of `contracts/install-and-errors.md` (`from err`). Keep the existing `# noqa: PLC0415`.
- [ ] T020 [US4] Edit `pyproject.toml`: remove `pandas>=3,<4` and `polars>=2,<3` and their comment from `dependencies`; add `pandas = ["pandas>=3,<4"]` and `polars = ["polars>=2,<3"]` to `[project.optional-dependencies]`; add the same two ranges to the `dev` dependency group. Then run `uv lock` (never edit `uv.lock` by hand) and `uv sync`. If `uv lock` fails because it cannot reach the network, stop this task, say so, and leave the rest of the story for the user. Check with `uv lock --check`.
- [ ] T021 [US4] Edit `README.md`: replace the sentence "pandas and polars are installed with quotable." (about line 32) with the install table from `contracts/install-and-errors.md` (a short list of the four `pip install` lines), keeping the paragraph about the frames' columns that follows it.
- [ ] T022 [US4] Run the base-install check from the Story 4 section of `quickstart.md` (`uv run --no-dev --isolated python ...`); it must print "base install: no pandas, as intended". If `--isolated` cannot resolve offline, say so and run `uv run pytest tests/test_frames.py tests/test_extra_fields_output.py tests/test_audit_output.py` instead and report that the base-install check was not run. **Checkpoint**: commit `pyproject.toml`, `uv.lock`, `quotable/table.py`, `README.md` and the test file as "Spec 015 story 4: pandas and polars are optional extras".

## Phase 7: User Story 5 - Notebook users know how to call the library (P3)

**Goal**: the README tells notebook users what to do (FR-014).

**Independent test**: read the README; the existing test `tests/test_entrypoint.py::test_the_pdf_can_be_a_string_and_the_async_twin_works` passes (it runs `extract_tables_async` inside a running loop).

- [ ] T023 [US5] In `README.md`, directly after the paragraph that says `extract_tables_async` takes the same arguments (about line 30), add a short passage: in a Jupyter notebook, which already runs an event loop, use `tables = await extract_tables_async(...)`; `extract_tables` starts its own loop and Python refuses that while one is running. Run `uv run pytest tests/test_entrypoint.py -q`. **Checkpoint**: commit `README.md` as "Spec 015 story 5: README note for notebooks".

## Phase 8: User Story 6 - No duplicate test file, no unused merge setting (P3)

**Goal**: one copy of the merge-check tests, and the half-equal rule removed with the fixture untouched (FR-015 to FR-017).

**Independent test**: one `test_merge_checks.py` exists; the default-rules merge decisions match the T002 baseline; `git status` shows nothing under `tests/data/synthetic/`.

- [ ] T024 [US6] Run `git rm tests/test_merge_checks.py` after confirming with `shasum tests/test_merge_checks.py tests/steps/test_merge_checks.py` that both files are still identical.
- [ ] T025 [US6] Edit `quotable/steps/merge.py`: delete the `equal_share` field and the comment above it in `Rules`, delete `half_equal_ok`, delete the `if not half_equal_ok(...): return fail("half_equal")` lines in `pair_verdict`, remove `half_equal |` from the failure-name comment in `Verdict`, remove "; no decision about the half-equal rule" from the `header_check` docstring, and remove `import math` (its only use was in `half_equal_ok`; run `uv run ruff check` to confirm). Keep `HeaderCheck.equal` and `MergeEvidence.equal_positions`. In `tests/steps/test_merge_checks.py` remove the `half_equal_ok` import, the `DEFAULT_RULES.equal_share == 0.0` assertion and `test_equal_share_is_a_setting`.
- [ ] T026 [P] [US6] Edit `tests/score_merge.py`: delete the `equal_share` line and the `equal_share, grid_tolerance` combination in `variants()` (keep the other sweeps) and the `equal_share=` part of `describe()`.
- [ ] T027 [P] [US6] Edit `tests/test_synthetic.py`: rename `test_the_rule_dependent_cases_are_there_to_decide_the_half_equal_rule` to `test_the_open_merge_cases_are_still_in_the_fixture`; keep its assertions. Do not touch `tests/synthetic.py`, `tests/synthetic_cases.py` or anything in `tests/data/synthetic/`.
- [ ] T028 [US6] Run `uv run python -m tests.score_merge --detail > $KIROCREW_SCRATCH/score_merge_after.txt` and compare the default-rules line with the baseline of T002 (the numbers must be identical; only the `equal_share=` text may differ). Run `git status --short tests/data/synthetic` (must print nothing), `uv run pytest tests/steps tests/test_synthetic.py -q`, and `grep -rn "equal_share\|half_equal_ok" quotable tests/*.py tests/steps` (must find nothing). Record the comparison in `## Results` in the spec. **Checkpoint**: commit as "Spec 015 story 6: remove the duplicate merge-check tests and the half-equal rule".

## Phase 9: Polish and cross-cutting

- [ ] T029 Update `AGENTS.md` in one pass (constitution: same change): in "Project state" add a Spec 015 sentence (what it fixed, the new test count from T032), change "pandas and polars are regular dependencies given as ranges" to optional extras `quotable[pandas]`/`quotable[polars]` with the `ImportError`, remove "(`Rules.equal_share` keeps it as a setting, default off)" and the claim that `just score-merge` reproduces the half-equal rows, and note that the review app's run cache is bounded by file size. In "Naming conventions" change "numbering continues from 013 (the next feature is 014)" to continue from 015 (next feature 016). In the file structure, update the `review/sources.py` line (render lock, run cache by size) and `steps/merge.py` if it names the removed rule.
- [ ] T030 Stage every new or changed file by name (so the hooks see them), then run `just hooks` (ruff check --fix, ruff format, ty). Fix what it reports and re-stage.
- [ ] T031 Run `just test` (`uv run pytest`). It must pass. Compare the count with 2,704: it should be 2,704 minus 36 plus the tests added by T003 to T005, T010, T013 and T018, and record that arithmetic and the final count in `## Results`.
- [ ] T032 Walk through `specs/015-audit-fixes/quickstart.md` once, story by story, and tick off what it expects. Anything you could not run (for example the base-install check) is written down in `## Results` as not run, with the reason.
- [ ] T033 Fill `## Results` in `specs/015-audit-fixes/spec.md`: the baseline and after numbers (queue timing, merge score line), the final test count, and one line per finding saying fixed, with the test that proves it. Commit `AGENTS.md`, the spec and the checklist as "Spec 015: AGENTS.md and results". Then run `speckit-converge`.

## Dependencies and order

- Phase 1 first (it captures numbers before code changes). Phase 2 is empty.
- Stories 1 to 6 are independent of each other; they touch different files, except `README.md` (stories 4 and 5, do them in order) and `AGENTS.md` (Phase 9 only).
- The order above follows priority. The plan suggests doing story 6 before story 4 so that a `uv lock` problem cannot block it; any order is valid.
- Inside a story: tests, then implementation, then the run, then the commit.
- Phase 9 comes last.

### Parallel opportunities

- T001 and T002.
- T004 and T005 (different test files), after T003.
- T014 and T015 (different source files); T016 follows T015.
- T026 and T027.

## Implementation strategy

- **MVP**: story 1 alone (T001 to T009) fixes the only finding that can fail a paid run.
- Then story 2 (the crash), story 3, and the rest as you approve. Each checkpoint leaves the suite green and the branch committed.
- If a task's check fails, stop and report; do not widen the change.
