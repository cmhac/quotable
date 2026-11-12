# Implementation Plan: Cost estimates, a cost limit and progress messages

**Branch**: `017-cost-estimate-progress` | **Date**: 2026-11-12 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/017-cost-estimate-progress/spec.md` (approved 2026-11-12, two clarifications)

## Summary

`extract_tables` gets two new arguments, `max_cost` (a limit in US dollars) and `progress` (messages on or off). A run then goes through three phases:

1. **Discovery.** Before the first request, print an estimate worked out from the page sizes and the model's published image-token rules. Run discovery with a progress line that shows cost so far.
2. **Sample.** Run the whole process (extraction, audit, recheck, extra-field checks) on 3 table pages, spread through the document, with the same progress line. Print a new estimate for the rest of the run from the measured cost per table page.
3. **Rest.** Run the same process on everything else, then print one final message.

Throughout, a **run meter** adds up the actual cost of every request as its usage arrives. If the total goes above `max_cost`, no new request starts, requests already in flight are allowed to finish (they are billed), and the run raises `CostLimitExceededError` with the settled total and how much to raise the limit by. The two estimate checks stop the run earlier when they can.

Approach, in the order the code changes:

- **`quotable/meter.py` (new)**: `RunMeter`, which holds the limit, the running total, per-phase and per-stage tallies, the in-flight count and the stop flag; and `price_of` / `CostModel`, which prices a token count through pydantic-ai's own `ModelResponse.cost()` (the same path the cost log uses).
- **`quotable/estimate.py` (new)**: the image-token rules per provider (research 2), a text-token guess, the discovery estimate (with a read-only cache probe) and the estimate for the rest of the run.
- **`quotable/progress.py` (new)**: `Reporter` and three sinks (notebook, terminal, plain lines). A notebook gets one updatable output block per phase through IPython's display handle (research 1).
- **`quotable/llm/client.py`**: `CachedClient` takes the meter: it refuses to start a request once the meter has tripped, records cache hits, and checks the meter after it has stored a paid answer, so the answer that crossed the limit is cached and a rerun does not pay for it again. It gains `peek` (read the cache without asking).
- **`quotable/pipeline.py`**: the part of `run_pipeline` after discovery becomes an inner function that takes the (table, page) jobs to run, so the sample and the rest use the same code. `extract_tables_async` builds the meter, the reporter and the cost model, and turns errors into closing messages.
- **`quotable/errors.py`, `quotable/__init__.py`**: `CostLimitExceededError`, a subclass of `BudgetExceededError`.
- **Docs**: README (new "Cost limit and progress" section, the "Not carried over yet" line about a dollar cap), AGENTS.md (state, file structure).

No prompt, request, cache key or saved-run format changes (FR-010). `run_pipeline` called without a cost context behaves exactly as today, so every existing offline test is unchanged (SC-007).

## Technical Context

**Language/Version**: Python 3.11+ (`requires-python = ">=3.11"`), type-checked with `ty`, linted with `ruff`

**Primary Dependencies**: pydantic-ai 2.54.0 (pinned; supplies `ModelResponse.cost()` and `infer_model`), genai-prices (comes with it), pymupdf (page sizes). No new dependency. IPython is used only if the process already has it loaded (`sys.modules`); it is never imported otherwise and is not added to `pyproject.toml`

**Storage**: none new. The cost log (`.quotable/cost/requests.jsonl`) and the saved run format are unchanged. The meter is in memory for the duration of one call

**Testing**: pytest, offline (fake clients that report a fixed cost per request, a fake IPython display). One opt-in live test records estimate against actual (needs the user's go-ahead, constitution III)

**Target Platform**: any machine that runs the library: scripts, terminals, Jupyter (classic, JupyterLab, VS Code, Colab). The notebook behavior is verified in none of them yet (research 1)

**Project Type**: Python library

**Performance Goals**: updates cost no request. The display is redrawn at most 4 times a second, and always once when a stage ends

**Constraints**: standard output stays free; messages go to stderr (terminal, file) or the cell output (notebook). The cost limit applies with messages off. A failure to draw never fails an extraction

**Scale/Scope**: runs of up to about a thousand table pages; the meter is a handful of counters, the display a few lines

No `NEEDS CLARIFICATION` items remain.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-checked after Phase 1 design.*

| Principle | Result |
|---|---|
| I. The text layer is the truth | Not touched. No grounding, position check or recheck rule changes |
| II. Fail closed on doubt | **Applied.** A limit with no known price refuses to start; a request with no usage under a limit stops the run (FR-009, FR-012b). A failed display or a failed cost-log write only warns or falls back, as the principle allows for side records |
| III. Offline-testable, live opt-in | **Met.** All behavior is tested with fake clients that report a cost. The one live test is opt-in and is not run without the user's go-ahead |
| IV. One entrypoint, explicit inputs | Two new arguments on the existing entrypoint; one new exported exception. `model` is still required and never read from the environment. Cache keys, prompts and the saved-run format are unchanged, and a test pins that |
| V. Generic | Nothing document-specific. The image-token rules are per provider and model, not per document |
| VI. Simplicity | See Complexity Tracking for the three places that go beyond the smallest change |

Re-check after Phase 1: unchanged. No violation.

## Project Structure

### Documentation (this feature)

```text
specs/017-cost-estimate-progress/
├── plan.md              # This file
├── research.md          # Phase 0: display approach, image-token rules, decisions
├── data-model.md        # Phase 1
├── quickstart.md        # Phase 1
├── contracts/
│   ├── public-api.md    # the new arguments, the new error and its fields
│   └── messages.md      # the text of every message, per sink
├── checklists/requirements.md
└── tasks.md             # Phase 2 (speckit-tasks)
```

### Source Code (repository root)

```text
quotable/
├── errors.py            # + CostLimitExceededError(BudgetExceededError)
├── __init__.py          # + CostLimitExceededError in the exports
├── meter.py             # NEW: RunMeter, CostModel, price_of, amounts (money formatting, round-up)
├── estimate.py          # NEW: image_tokens (per provider), text_tokens, estimate_discovery, estimate_rest, CacheProbe
├── progress.py          # NEW: Reporter, NotebookSink, TerminalSink, PlainSink, NullSink, choose_sink
├── pipeline.py          # run_pipeline: optional CostContext, phases, sample; extract_tables(+_async): max_cost, progress
└── llm/client.py        # CachedClient: meter hooks, peek, hit counts

tests/
├── test_meter.py        # NEW
├── test_estimate.py     # NEW (image rules pinned to the examples in the providers' documentation)
├── test_progress.py     # NEW (sinks, throttle, no control codes in a file, notebook block count)
├── test_cost_limit.py   # NEW (the whole pipeline with a priced fake client: every acceptance scenario)
├── llm/test_cached_client_meter.py  # NEW (trip, in-flight, cache of the crossing answer, keys unchanged)
├── conftest.py          # + PricedClient (a FakeClient that reports a fixed cost) and a fake IPython
└── live/test_live_cost_estimate.py  # NEW, opt-in: estimates beside actual cost
```

**Structure Decision**: three new flat modules at the package root, beside `storage.py` (which already holds the cost log). They are cross-cutting (client, pipeline, errors), so they do not belong in `steps/` or `llm/`. `llm/client.py` and `pipeline.py` change; no step module changes.

## Design

### The run meter (`quotable/meter.py`)

One `RunMeter` per `extract_tables_async` call, used on the event-loop thread only (no locks).

- State: `limit` (`Decimal | None`), `total` (`Decimal`), `phase` (`"discovery" | "sample" | "rest"`), tallies keyed by (phase, stage) holding requests, cache hits, input and output tokens, cost; `in_flight`; `stopped` (the reason, once set); `progress` (per stage: done, total, `upper_bound` flag).
- `add(request, usage, cost)` is the `on_usage` callback of `PydanticAIClient` (chained with `CostLog.record_usage`). It adds `cost` to the totals. With a limit set, a request with no usage or no price sets `stopped = "unmetered"`; a total above the limit sets `stopped = "spent"`. It also remembers the cost against `id(request)` so `CachedClient` can attach it to the cache key.
- `begin()` / `end()` bracket a paid request (`in_flight`). `settled()` is an awaitable that returns when `in_flight == 0`.
- `check()` raises `CostLimitExceededError` if `stopped` is set. It is called at the start of every `CachedClient.ask`, and after a paid answer has been stored.
- `paid(key, request)` and `hit(key, stage)` keep, for the sample phase, a dict from cache key to cost, and count how much of it the rest of the run asked for again. The difference is "not reused" (FR-017).
- Money is `Decimal` throughout. Display and rounding live in two helpers: `dollars(x)` (enough decimals that a total over the limit never prints as equal to it) and `round_up(x)` (for "raise the limit by").

`CostModel` bundles what the estimates need and what the meter should not know about providers: `name` (`provider:model`), `price(input_tokens, output_tokens) -> Decimal | None`, and `image_tokens(width_px, height_px, detail) -> int | None`. `CostModel.for_model(model)` builds it with `infer_model` and `ModelResponse(...).cost()`. If `infer_model` fails (no API key set) the price is unknown and the reason is kept for the message.

### The client (`quotable/llm/client.py`)

`CachedClient.__init__` gains `meter: RunMeter | None = None`. `ask` becomes:

1. compute the key; with a meter, `meter.check()` first (a tripped meter stops cache hits too, so the stop is at once);
2. cache hit: count it (`meter.hit`), return;
3. `max_requests` check as today;
4. `meter.begin()`; ask the inner client; `meter.end()` in a `finally`;
5. store the answer in the cache, `meter.paid(key, request)`, then `meter.check()`. The request that crossed the limit is cached, so a rerun with a higher limit does not pay for it, and then raises.

`peek(request)` returns the cached answer or `None`, and `ask` uses it. With no meter, `ask` behaves as before.

### The estimates (`quotable/estimate.py`)

Image tokens, from the providers' documentation (research 2): OpenAI patch models (the multiplier table and the per-detail patch budgets), OpenAI tile models, Anthropic patches with the tier cap. A model not in the table returns `None`, and the estimate says no rule is known. Text tokens are `len(text) / 4`, labelled a guess (a `shortcut:` comment).

- `estimate_discovery`: render sizes from page rectangles at 150 dpi, `detail="high"`, as discovery sends them. The cache is probed by running the real `discover` against a `CacheProbe` client that answers from `CachedClient.peek` and raises on a miss; the answered requests are the cached ones, so the estimate covers only the windows from the first miss on. An allowance for the answer is a constant per page (labelled), and a constant for the "known tables" text in later windows.
- `estimate_rest`: from the sample's tallies. Per table page: `c` = sample cost / pages in the sample, and `e` = the extraction share of it. Rest = `(T - N) * c + N * (c - e)`, which counts the sample pages' audit and recheck again because they may not be reused (spec, Assumptions). Expected total = spent so far + rest. If any sample request came from the cache the estimate is marked as possibly low.

### The phases (`quotable/pipeline.py`)

`run_pipeline` gains one optional argument, `costs: CostContext | None`. `CostContext` holds the meter, the reporter, the cost model and the cache probe function. Without it nothing below happens.

```text
read layers, OCR, check sizes, render pages           (unchanged)
estimate_discovery -> reporter.estimate -> limit check -> phase "discovery"
discover(...)                                          (unchanged)
bands and layouts for ALL tables (from the full discovery)
jobs = [(table, page) ...] in table then page order
if costs and len(jobs) > SAMPLE_PAGES:
    sample = spread(jobs, 3)                           # first, middle, last
    phase "sample": announce; process(sample) ; discard the tables
    estimate_rest -> reporter.estimate -> limit check
phase "rest": process(all jobs)
final message
```

`process(jobs)` is the existing code after discovery moved into an inner function: extraction for the jobs, grounding, audit, extra fields (restricted to those pages), merge and recheck. For the sample, merge is skipped (it makes no request), and its tables are thrown away. The bands and layouts are computed once from the full discovery and then filtered to the sample pages, so a sample page on a shared page is grounded against the same band, and a page without a header inherits the same layout as in the full run. Extraction requests of the sample are identical to the full run's, so they are cache hits there. Audit and recheck requests of the sample depend on the whole table (furniture, position check) and may differ; the "not reused" figure says how many.

### The display (`quotable/progress.py`)

`Reporter` turns events into text and hands it to one sink. Events: `estimate`, `announce`, `stage_progress`, `phase_end`, `final`, `closing`. The meter pushes progress; the reporter throttles redraws to 4 a second and always draws when a stage ends.

- **Notebook** (IPython already loaded and its shell is a `ZMQInteractiveShell`): one block per phase, `display({"text/plain": text}, raw=True, display_id=...)`, updated with `update_display`. The block holds the phase's estimate and announcement lines, then a live status line. Four blocks in a run: discovery, sample, rest, final.
- **Terminal** (`stderr.isatty()`): fixed lines are printed; the live line is rewritten with a carriage return and a clear-line code, and cleared before any fixed line is printed.
- **Plain** (anything else): fixed lines only, plus the live line at the start and end of each stage.
- **Null** (`progress=False`).

Any exception from a sink switches to the plain sink for the rest of the run (FR-020). Messages go to stderr (terminal, plain) or the cell output (notebook). Text and layout are in [contracts/messages.md](contracts/messages.md).

### Errors and the closing message (`extract_tables_async`)

```text
costs = build (meter, reporter, cost model)
if limit set and price unknown -> raise CostLimitExceededError(reason="unpriced")   # before anything
try:    tables = run_pipeline(..., costs)
except CostLimitExceededError as e:
    await meter.settled()           # in-flight requests finish and are counted
    e = e.settled(meter)            # rebuild with the settled total, over, raise_by, finish_by
    reporter.closing(e); raise e
except Exception:                   # any other failure: closing message, then the same error
    reporter.closing(None); raise
reporter.final(...)
```

The stop is immediate in the sense that no new request starts: every `CachedClient.ask` raises at its first line once the meter has tripped, including tasks that were only waiting for the run's gate of 4. `asyncio.gather` leaves the other tasks running after the first error; they either finish their request (and are counted) or stop at that first line.

## Complexity Tracking

| Beyond the smallest change | Why needed | Simpler alternative rejected because |
|---|---|---|
| Three new modules, not one | Meter, estimates and display change for different reasons and are tested apart | One 500-line module mixing provider rules, state and printing would be harder to read and test |
| Waiting for in-flight requests before raising | FR-012 says the error total is what the provider will bill | Raising at once would show a total that is too low and a "raise by" that is not enough |
| `peek` plus a read-only discovery run to find cached windows | FR-002 says cached requests are left out of the estimate | Counting every window as new would print a cost for a run that is free, which is the case the cache exists for |
| `progress=False` | The library prints by default; scripts and servers need silence | Not asked for; added because a library that writes to stderr with no way off breaks callers. The user may remove it |
