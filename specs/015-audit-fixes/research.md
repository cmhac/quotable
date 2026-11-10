# Research: Audit fixes

Each section: the decision, why, and what else was considered. Measurements were taken on
2026-11-10 on the development machine (macOS, Apple Silicon, Python 3.11.14) with the demo project
from `python -m tests.review_demo` (8 documents).

## R1. The recheck and the request limit (story 1)

**Today**: `run_pipeline` makes one `asyncio.Semaphore(4)` (`MAX_CONCURRENT_REQUESTS`). Extraction
and the omission audit use it. `resolve_extra_fields` makes a second semaphore for the second
looks. `recheck_table` (called through `asyncio.gather` over all tables) and `recheck_fields` call
`client.ask` with no limit. `recheck_table` also renders every flagged page's image up front, so a
150-page table holds 150 images at 300 dpi (about 540 KB each, 80 MB) before the first request.

**Decision**:

- `recheck_table(table, pdf, client, images, gate)` and `recheck_fields(printed, layers, pngs,
  fields, client, gate)` take the semaphore as a required argument, as `audit_table` already does.
  Each page's request runs inside `async with gate:`.
- `recheck_table` renders each page inside that gated task with `render_page(pdf, page,
  images.dpi)` instead of opening the PDF once and rendering all pages first. `render_page` calls
  the same `render_png(document[n - 1], dpi)`, so the image bytes, and therefore the cache keys,
  are identical (checked by reading both functions in `quotable/steps/extract.py`). This also
  holds at most 4 images at a time.
- `resolve_extra_fields` stops creating its own semaphore and receives the run's. It is called
  only from `run_pipeline`. The stages run one after another, so even two semaphores could not
  exceed 4, but FR-002 asks for one shared limit and a single object is the easy way to keep that
  true when a stage is added.
- Existing callers to update: `tests/steps/test_extra_fields_recheck.py` (`run`),
  `tests/test_extra_fields_output.py` (one `recheck_table` call) and
  `tests/live/test_live_audit.py` (one call, which already passes a semaphore to `audit_table`).

**Why it is enough**: `CachedClient` checks the request cap before it awaits, so waiting for a slot
cannot let more new requests start than `max_requests` allows (spec edge case).

**Alternatives**:

- A semaphore inside `CachedClient.ask`, which would gate every stage in one place and let the
  per-stage semaphores go. It is the better end state. Rejected for this spec because it also
  gates discovery and the cache hits, changes `audit_table`'s signature and the shape of the
  extraction code, and is a refactor nobody asked for. It is noted here as a possible later
  simplification.
- A default `gate=None` argument. Rejected: it adds a branch and leaves a way to call the recheck
  without the limit.

## R2. Rendering in the review app (story 2)

**Today**: `ThreadingHTTPServer` answers each request on its own thread. `sources.page_png` holds
`_lock` only around cache reads and writes; `pymupdf.open` and `render_png` run unlocked, so two
page requests can render at once. [PyMuPDF's documentation](https://github.com/pymupdf/PyMuPDF/blob/main/docs/recipes-multiprocessing.rst)
says it does not support running on multiple threads and that doing so may give wrong results or
crash. `page_png` is the only place in `quotable/review/` that calls PyMuPDF (checked with a
search for `pymupdf`, `render_png` and `render_page`).

**Decision**: one module-level `_render_lock = threading.Lock()` in `sources.py`, held in a `with`
block around the open and render. A failing render leaves the block, so the lock is released
(FR-005). A second request for the same page may render it again after waiting; the result is the
same and the cost is one extra render, so the cache is not re-checked inside the lock.

**Alternatives**: a single-thread executor for renders (more code, same effect); pre-rendering
pages in the background (more behavior than asked); running the server single-threaded (slows
every other request).

**Test**: monkeypatch `quotable.steps.extract.render_png` (imported inside `page_png`, so the
patch takes effect) with a function that records how many calls overlap and sleeps briefly; call
`page_png` from 20 threads for different pages; assert the maximum overlap is 1 and every result is
returned. A second test makes the patched render raise once and checks the next call still works.

## R3. The review queue (story 3)

**Profile** of a repeated `get_queue` on the demo project (cProfile, 0.47 s with the profiler;
0.40 s without):

| Part | Time | Share |
|------|------|-------|
| `_scoped_items` (called twice: by `population` and by `counts_by_status`) | 0.27 s | 58% |
| `sources.load` → `load_run` → JSON parsing (7 of 8 runs miss the 4-run cache) | 0.18 s | 39% |

So the audit's guess (parsing) was only part of it.

**Memory**: a parsed run holds about 5 times its file size (`tracemalloc`): the 3,024-row run is
5.7 MB on disk and 28.5 MB parsed; the others are 0.01 to 0.31 MB on disk and 0.1 to 1.4 MB parsed.

**Decision**:

- Bound the run cache by bytes of run files, not by a count of 4: `_RUN_BYTES = 64 * 1024 * 1024`.
  The size of a run is already known, because `load` stats `run.json` and `tables.json` for its
  freshness stamp. Eviction drops the least recently used run while the total is over the budget
  and more than one run is cached, so a single run larger than the budget is still kept (spec edge
  case). 64 MiB of files is about 320 MB parsed; 50 runs fit if they average 1.3 MiB.
- `get_queue` builds the item list once. `_scoped_items` becomes public as `scoped_items`;
  `population` and `counts_by_status` keep their signatures and call it (their other callers and
  tests do not change); `get_queue` calls `scoped_items` once and derives the status counts and
  the population from the one list. The exact helper shape is a task detail; the requirement is
  one build per request (FR-009a).

**Alternatives**: a count of 64 instead of 4 (one number, but a project of 64 large runs would
hold gigabytes); caching the population by `(file stamps, settings)` (a second cache to
invalidate, for 0.13 s that falls out of the first fix); a memory limit measured with
`tracemalloc` (slow and platform-dependent).

**Expected result**: 0.40 s becomes about 0.15 s, measured in the task and recorded in the spec's
results; the pass mark is "at most half" (SC-003). If it is not reached, the task reports what
else is slow instead of declaring success.

**Test**: count calls to `load_run` (patch it in `sources`) across two `get_queue` requests on a
project of 10 generated runs: zero on the second. Touch one run file and check that only that run
is read again and the answer changes. Fill past the budget with a small patched budget and check
the oldest is dropped. A count test on `scoped_items` calls per `get_queue` (one).

## R4. pandas and polars as extras (story 4)

**Today**: both are in `dependencies` (spec 008, requirement 7). `quotable/table.py` imports them
only inside `to_pandas()` and `to_polars()`; nothing else in the package imports either. Tests
import both at the top of three files (`test_frames.py`, `test_audit_output.py`,
`test_extra_fields_output.py`). `uv.lock` already holds pandas 3.0.6 and polars 2.0.0.

**Decision**:

- `pyproject.toml`: remove both from `dependencies`; add `pandas = ["pandas>=3,<4"]` and
  `polars = ["polars>=2,<3"]` to `[project.optional-dependencies]`; add both to the `dev` group so
  `uv sync` and CI still run the frame tests. Same ranges as today. No combined extra.
- Re-lock with `uv lock` (never by hand). If it needs the network and there is none, stop and say so.
- In `table.py`, each method wraps its import: on `ImportError`, raise `ImportError` with the text
  in [contracts/install-and-errors.md](contracts/install-and-errors.md), `from` the original.
  Two short `try` blocks, not a shared helper, so the type checker still sees `pd` and `pl` as the
  real modules.
- Tests: with `sys.modules["pandas"] = None` (which makes `import pandas` raise `ImportError`),
  `to_pandas()` raises with the extra's name in the message; the same for polars.
- A base install is checked once by hand (quickstart). A CI job for it is not added (YAGNI); the
  `ImportError` test and the existing test that `import quotable` loads neither library cover the
  code side.

**Alternatives**: a combined `frames` extra (the user asked for neither); keeping them required
(rejected by the request); a try/except helper returning the module (loses typing).

## R5. Notebook note (story 5)

`extract_tables` calls `asyncio.run`, which raises `RuntimeError` when an event loop is already
running (documented Python behavior; Jupyter runs one). The async twin exists and is exported.
`tests/test_entrypoint.py::test_the_pdf_can_be_a_string_and_the_async_twin_works` runs
`extract_tables_async` through `asyncio.run`, so the coroutine executes inside a running loop. That
already satisfies FR-014's test requirement. The task is the README passage only. I did not run the
sync function in a real notebook; the claim rests on the Python documentation.

## R6. The duplicate test file (story 6, finding 6)

`tests/test_merge_checks.py` and `tests/steps/test_merge_checks.py` have the same SHA-1 prefix
(`3e1cc1b687`), 359 lines and 35 tests each; both are tracked. It is the only duplicated test file
name in `tests/`. Spec 012 moved the tests into folders that mirror the package, and
`tests/steps/` is that home. `git rm tests/test_merge_checks.py`. The suite drops by exactly 35.

## R7. Removing the half-equal rule (story 6, finding 7)

**What goes**: in `quotable/steps/merge.py`, `Rules.equal_share` and its comment, `half_equal_ok`,
the `if not half_equal_ok(...)  return fail("half_equal")` branch, `half_equal` in the comment that
lists failure names, the words "no decision about the half-equal rule" in the `header_check`
docstring, and `import math` (its only use is in `half_equal_ok`). In
`tests/steps/test_merge_checks.py`: the `half_equal_ok` import, the `DEFAULT_RULES.equal_share`
assertion and `test_equal_share_is_a_setting`. In `tests/score_merge.py`: the `equal_share` rows of
`variants()` and the `equal_share=` text in `describe()`.

**What stays**:

- `HeaderCheck.equal` and `MergeEvidence.equal_positions`. They are evidence (how many header
  positions have identical words), saved in runs, shown in the review app and tested there. They
  are not the rule.
- The synthetic fixture files, their `half_equal` probe labels and the generator, so
  `just synthetic` and its freshness test are untouched. `tests/test_synthetic.py` keeps a test that
  the 50 or more open cases exist, renamed and reworded so it no longer says they decide a rule.

**No merge decision changes**. With the default `equal_share = 0.0`, `half_equal_ok` returns
`same_count and bool(token_sets) and equal >= 0`. The check just above it in `pair_verdict`
already returns `fail("count")` when `not head.same_count or not head.token_sets`, so
`half_equal_ok` can never be false at that point. Removing it is behavior-neutral by construction;
the test that merge decisions on all fixture documents are the same is kept as a guard (FR-017).

**Stored data**: the verdict's failure name is not saved anywhere. `Table.merged` holds only
successful merges, with evidence fields that stay. The plan's assumption that nothing stored names
the rule holds.

## R8. Counting the tests

The offline suite has 2,704 tests today. Story 6 removes 35 (duplicate) and 1 (`test_equal_share_is_a_setting`);
the other stories add tests, which the task list names. The final count is whatever those add up
to; SC-005 asks only that every change be accounted for.
