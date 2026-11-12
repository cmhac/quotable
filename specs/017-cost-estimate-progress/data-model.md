# Data model: spec 017

Everything here is internal and in memory, for the duration of one `extract_tables_async` call. Nothing is stored on disk, and the cost log and saved-run formats do not change. The one public type is `CostLimitExceededError` ([contracts/public-api.md](contracts/public-api.md)).

## RunMeter (`quotable/meter.py`)

| Field | Type | Meaning |
|---|---|---|
| `limit` | `Decimal \| None` | The user's `max_cost`. `None`: nothing is stopped for cost |
| `total` | `Decimal` | Actual cost of every paid request so far in this call |
| `phase` | `"discovery" \| "sample" \| "rest"` | Set by the pipeline |
| `tallies` | `dict[(phase, stage), Tally]` | See below |
| `in_flight` | `int` | Paid requests started and not yet finished |
| `stopped` | `None \| "spent" \| "unmetered"` | Set once; never cleared |
| `progress` | `dict[stage, Progress]` | `done`, `total`, `upper_bound` (true for audit and recheck) |
| `sample_paid` | `dict[cache key, Decimal]` | What each paid sample request cost |
| `sample_reused` | `Decimal` | Cost of the sample requests the rest of the run asked for again |
| `started` | `float` | `time.perf_counter()` at the start, for the final message |

Rules:

- `total` equals the sum of the tallies' costs. A request whose price is unknown adds its tokens to the tally and nothing to `total`; with a limit set that request trips the meter first (`unmetered`).
- `stopped = "spent"` is set when `total > limit` (strictly). It is checked every time a request's usage arrives.
- Once `stopped` is set, `check()` raises on every later call. There is no state in which a request starts after that.
- `in_flight` is non-negative; `settled()` completes when it is 0.

**Tally**: `requests`, `cache_hits`, `input_tokens`, `output_tokens`, `cost` (`Decimal`), `unpriced` (requests with no price).

## CostModel (`quotable/meter.py`)

| Field | Type | Meaning |
|---|---|---|
| `name` | `str` | `provider:model-name`, as the cost log writes it |
| `price` | `(int, int) -> Decimal \| None` | Input and output tokens to dollars; `None` when no price is known |
| `image_tokens` | `(int, int, str) -> int \| None` | Width and height in pixels and the image detail to tokens; `None` when no rule is known |
| `why_unpriced` | `str` | The cause when `price` is unknown (for example "set OPENAI_API_KEY") |

## Estimate (`quotable/estimate.py`)

| Field | Type | Meaning |
|---|---|---|
| `label` | `"discovery" \| "rest"` | |
| `requests` | `int` | Requests the figure covers |
| `cached` | `int` | Requests left out because their answers are cached |
| `input_tokens`, `output_tokens` | `int \| None` | `None` when the image rule is unknown |
| `cost` | `Decimal \| None` | `None` when tokens or price are unknown |
| `basis` | `str` | One sentence: what was counted |
| `unavailable` | `str \| None` | Why there is no figure |
| `per_page` | `Decimal \| None` | Only for `rest`: the sample's measured cost per table page |
| `expected_total` | `Decimal \| None` | Only for `rest`: spent so far plus the rest |
| `possibly_low` | `bool` | Only for `rest`: some sample requests came from the cache |

An estimate never changes a request, a prompt or a cache key (FR-010).

## SamplePlan (`quotable/pipeline.py`)

The ordered list of (table index, page) jobs, and the chosen subset: positions `round(i * (T - 1) / 2)` for i in 0, 1, 2. Empty when `T <= 3`.

## CostContext (`quotable/pipeline.py`)

What `run_pipeline` receives to turn the new behavior on: `meter`, `reporter`, `cost_model`, `peek` (the cache probe). `None` means today's behavior exactly.

## Reporter and sinks (`quotable/progress.py`)

`Reporter(sink, meter)` has the events `estimate`, `announce`, `stage_progress`, `phase_end`, `final`, `closing`. A sink implements `fixed(text)` (a line that stays), `live(text)` (the status line that is rewritten) and `end_phase()`. `NotebookSink` keeps one `display_id` per phase. Redraws are throttled to 4 a second.

## Final summary (built from the meter and the tables)

Total cost; the estimates beside it (discovery, rest) and the sample's cost; new requests and cache hits per stage; pages in the PDF, tables, table pages; the sample's cost not reused (`sample paid - sample_reused`); elapsed time. After a failure: the total, the stage and its progress.
