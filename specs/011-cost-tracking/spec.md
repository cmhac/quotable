# 011 - Cost tracking and `quotable cost-report`

Status: draft; all open questions answered by the user; waiting for the user's review of the spec.

## Summary

Every time quotable sends a request to a model, it writes down what that request cost. The
records pile up across all runs in `.quotable/cost/`, and a new command prints the totals.
This spec also gives `.quotable/` a layout: one subfolder per kind of thing quotable keeps, so
the cache is `.quotable/cache/`, the costs are `.quotable/cost/`, and clearing one never
touches the other. Other kinds of project data can get their own subfolder later:

```console
$ quotable cost-report
Cost report for .quotable/cost/requests.jsonl

Runs:      7
Requests:  412 paid, 0 unpriced
Tokens:    3,204,118 in, 188,430 out
Total:     $9.87

By model            Requests      In tokens    Out tokens        Cost
openai:gpt-5.1           400      3,100,000       180,000       $9.40
openai:gpt-5-mini         12        104,118         8,430       $0.47
```

No setting to turn on, no new Python API to learn. A user who never runs the command loses
nothing.

## Motivation

- Model requests are the only thing in quotable that costs money, and a long document is
  hundreds of them. Today the only guard is `max_requests`, a count, and the original project's
  dollar cap was left out (README, "Not carried over yet").
- Answers are cached, so a re-run is free and the bill is spread over many runs. Nobody can tell
  afterwards what a project spent, because the cache holds answers and not what they cost.
- Tracking is useful on its own, before any decision about a dollar cap.

## Requirements

1. **Record every paid request.** When a request reaches the model (a cache miss), one record is
   appended to `.quotable/cost/requests.jsonl` in the current working directory. One project, one
   folder, one file: that is what "all runs for a given project" means. The location does not
   depend on `cache_dir`: a run that caches elsewhere still records its costs in the project's
   `.quotable/`.
2. **`.quotable/` is organised by subfolder.** The cache moves to `.quotable/cache/` (it used to
   fill `.quotable/` itself) and the costs live in `.quotable/cost/`. Clearing the cache means
   deleting `.quotable/cache/`, and `.quotable/cost/` survives. The rule going forward: each
   kind of thing quotable keeps in a project gets its own subfolder of `.quotable/`, so
   `.quotable/` can hold more later without them getting in each other's way. See "Folder
   layout" in Design. A `cache_dir` the caller names is still used exactly as given (the cache
   is that folder, nothing is added under it).
3. **A record is one JSON object per line** with these fields, and no document content:

   | Field | Meaning |
   | --- | --- |
   | `v` | Record format version, `1` |
   | `time` | When the answer came back, UTC, ISO 8601 |
   | `run` | Random id shared by every record of one `extract_tables` call |
   | `stage` | `schema`, `extract` or `recheck` (the request's stage) |
   | `model` | The model name as the cache key uses it (`provider:model-name`) |
   | `input_tokens`, `output_tokens` | As the provider reported them |
   | `cache_read_tokens`, `cache_write_tokens` | The provider's own prompt caching, `0` if none |
   | `cost_usd` | The price calculated when the record was written, or `null` if unknown |

   The record holds no prompt, answer, page text, file name or path, so the file is safe to
   share on its own. (`.quotable/.gitignore` still keeps it out of git when quotable made the
   folder.)
4. **Price source: pydantic-ai's own cost tracking.** Each request's tokens come from the
   pydantic-ai run result (`result.usage()`) and its price from `result.response.cost()`, which
   pydantic-ai computes with `genai-prices`. There is no new dependency and no price table in
   quotable. The cost of each request is calculated and stored when that request's record is
   written, so a later price update never rewrites history. **The report only sums the stored
   per-request costs**; it never prices anything itself. The figure is an estimate: only as
   right as the price data in the installed `genai-prices`.
5. **Unknown price is not an error.** A custom `Model` instance or a new model may not be in
   `genai-prices`. The record is still written, with the tokens and `cost_usd: null`. The report
   counts these requests as "unpriced" and says the total leaves them out.
6. **Cached answers cost nothing and write nothing, and the report does not count them.** A
   request answered from the cache adds no record. Re-running a finished document adds no cost,
   and the report does not change. The report covers what was spent over the project's history,
   not how often the cache helped.
7. **Recording can never break an extraction.** If the file cannot be written, or a model
   returns no usage, quotable prints one warning to stderr (once per run) and carries on. A
   failed request (the model raised, or `BudgetExceededError`) writes no record.
8. **Concurrent requests and runs are safe.** Requests run concurrently, and two runs may share
   a project folder. Each record is written with a single append of one whole line (a record
   is far below the size the operating system appends atomically), so lines never interleave.
   No lock file.
9. **Nothing else changes.** The request cache key, prompts, answers, `max_requests` and its
   counting, the public API and `quotable.__all__` stay as they are. A model answer is cached
   exactly as before; only the default folder it sits in moves (requirement 2).
10. **`quotable cost-report`** is a new console command for people who install quotable
    (`[project.scripts] quotable = "quotable.cli:main"`; `python -m quotable` works too). It
    reads the cost file and prints the report above to stdout. It never calls a model, never
    needs an API key, and never creates or changes anything.
   - **Where it looks:** `.quotable/cost/requests.jsonl` in the current directory, or
     `--dir PATH` to read another project's `.quotable/` folder.
   - **What it prints:** the number of runs; the number of paid requests and, separately, the
     number of unpriced ones; total input and output tokens; the total cost; and a table of the
     same numbers per model, largest cost first. Costs are in US dollars, to the cent (two
     decimals) for a total of a dollar or more, otherwise to four decimals so small runs do not
     show as `$0.00`.
   - **No records yet** (the file or folder does not exist, or is empty): print
     `No cost records found in <path>. Costs are recorded when quotable sends a request to a
     model.` and exit 0. This is a normal state, not a failure.
   - **A damaged line** (not JSON, or missing fields) is skipped. The report ends with
     `Skipped N unreadable lines.` so the user knows the totals may be low. It never raises on
     a bad line.
   - **Exit codes:** 0 on success and on "no records"; 2 for a usage error (unknown option;
     argparse's default). A folder that exists but cannot be read exits 1 with a message
     naming the path.
   - The report is plain text, one fixed layout, no colour, no flags for other formats (see
     Out of scope).
11. **The command stays light.** It uses the standard library (`argparse`, `json`) only. It
    does not import pandas, polars, PyMuPDF or pydantic-ai itself. (Importing
    `quotable.cli` runs `quotable/__init__.py`, which imports the pipeline; making that lazy is
    not part of this spec, and the task measures the start-up time so it is a known number.)

## Design

### Code

- **`src/quotable/costs.py` (new, internal).** Three small pieces, no pandas:
  - `CostRecord`, a frozen dataclass with the fields of requirement 3, plus `to_line()` and
    `from_line()`.
  - `CostLog(directory, run_id)`, with `record(request_stage, model, usage, cost)`. It builds a
    record and appends the line (requirement 8), catching `OSError` and warning once
    (requirement 7).
  - `summarize(path) -> CostSummary` and `format_report(summary, path) -> str`, so the report is
    a pure function of the records and can be tested without a terminal.
- **Getting the usage out of the model.** `LLMClient.ask` returns only the answer, and nothing
  above the model knows the tokens. The pydantic-ai client already holds `result.usage()` and
  `result.response.cost()` for each request, so it is the one place to read them. Design: the
  `PydanticAIClient` takes an optional `on_usage` callback, called once per request with the
  request, its usage and its cost (`None` if the price lookup raises `LookupError` or the usage
  is empty). `extract_tables` builds a `CostLog` for the project's `.quotable/` folder and passes
  its method as the callback. Nothing is added to the `LLMClient` protocol, so fake clients in
  the tests are unchanged, and the callback is not part of `identity`, so cache keys do not
  change. Because `CachedClient` calls the inner client only on a miss, requirement 6 holds
  without any extra code.
- **Request retries.** pydantic-ai retries a model answer that fails output validation inside one
  `agent.run`; `result.usage()` sums those, so one record holds the cost of the whole `ask`,
  retries included.
- **`src/quotable/cli.py` (new).** `main(argv=None) -> int` with an `argparse` sub-command
  `cost-report` and `--dir`. `src/quotable/__main__.py` calls it.
- **Run id.** One `uuid4().hex` per `extract_tables_async` call, created next to the client.
- **File.** `.quotable/cost/requests.jsonl` (one line per paid request; the folder is for costs,
  the file name says what a line is), created with its folders on the first record. When
  quotable creates `.quotable/` it writes `.quotable/.gitignore` containing `*`, as
  `resolve_cache_dir` does today, which covers every subfolder.

### Folder layout

```
.quotable/
├── .gitignore        written when quotable creates the folder; contains *
├── cache/            model answers (<sha256>.json) and ocr/ ; safe to delete
└── cost/
    └── requests.jsonl   one line per paid request; kept when the cache is cleared
```

Today the cache *is* `.quotable/`, and `cache.py` documents "deleting the folder starts over",
so a cost file placed in `.quotable/` would go with it. Giving each kind of data its own
subfolder fixes that and sets up the folder for more later.

- Default cache: `.quotable/cache/` (was `.quotable/`). Costs: `.quotable/cost/`.
  Clearing the cache is `rm -rf .quotable/cache`; the README says so.
- A `cache_dir` the caller passes is used as given, as today. Costs still go to the project's
  `.quotable/cost/`, never into `cache_dir`.
- `resolve_cache_dir`'s docstring, the `.gitignore` rule it writes (still `*`, written into
  `.quotable/`), and the README/AGENTS.md wording change with it. `DEFAULT_DIR_NAME` stays
  `.quotable`; new constants name `cache` and `cost`.
- **One-time move of an existing cache.** Existing users have answers (which cost money) loose
  in `.quotable/`: `<64 hex characters>.json` files and the `ocr/` folder. When the default
  `.quotable/cache/` does not exist yet and such entries do, `resolve_cache_dir` moves them
  into it (`os.replace`, same filesystem, one entry at a time). Only those two kinds of entry
  move; `cost/`, `.gitignore` and anything else are left alone. An entry that cannot be moved
  is left where it is and costs one cache miss; a warning on stderr says how many. Two runs
  starting at once can both try the move; `os.replace` of an entry that is already gone is
  ignored, so the result is the same.

### Alternatives considered

- **A SQLite database or a CSV.** Rejected: the append-only text file needs no schema or
  migration, survives a crash mid-write (at worst the last line is bad and is skipped), and
  can be read with `jq` or polars.
- **One cost file per run.** Rejected: the user asked for totals across runs; one file makes
  that a single read.
- **Store cost inside each cached answer file.** Rejected: it would change the cache's file
  format, a cache hit would then appear to cost money again, and clearing the cache would erase
  the costs.
- **Keep the costs loose in `.quotable/` next to the cache files.** Rejected (user
  decision): clearing the cache by deleting `.quotable/` would erase the cost history.
- **Compute cost at report time from stored tokens.** Rejected (user decision): the cost of each
  request is stored when written and the report sums them, so totals do not drift when prices
  update. The tokens are stored too, so a future command could reprice.
- **Count cache hits.** Rejected (user decision): the report is about what the project spent
  over its history, not cache statistics.
- **`--format json`/`--csv`.** Rejected for now; the file is already JSON Lines.

## Out of scope

- A dollar cap (`max_cost`) that stops a run. This spec only measures; a cap can build on it.
- Reporting money saved by the cache, cost per document or per table, a date filter, or
  `--by-stage`/`--by-run` breakdowns. (`stage` and `run` are recorded so these can be added.)
- Other output formats, colour, or any machine-readable report.
- Tracking OCR (PaddleOCR runs locally and costs no API money).
- Back-filling cost for requests made before this feature (they are in the cache but their
  token counts were never kept).
- Rotating, trimming or deleting `.quotable/cost/`. quotable never deletes it; the user does, by
  hand, to start the cost history over.
- Anything else in `.quotable/` beyond `cache/` and `cost/`. The layout leaves room for it; this
  spec adds nothing more.
- Putting costs anywhere but the project's `.quotable/` (for example one shared file for all
  projects, or a folder next to a custom `cache_dir`).
- Making `import quotable` lighter.

## Tests

All offline; new files `tests/test_costs.py` and `tests/test_cli.py`. No real model: the tests
that need usage call the `on_usage` path with a pydantic-ai `TestModel`/`FunctionModel` (which
report usage), and the formatting tests build records directly. (A fake model is fine here:
these tests check the bookkeeping, not how a model answers.)

- A paid request appends exactly one valid record with the fields above; the stage and model
  are right.
- A second identical run (all cache hits) appends nothing and the report is unchanged.
- Records of two runs share the file and have two different `run` ids; one run's records share
  one id.
- `cost_usd` is `null` and the tokens are kept when the price lookup fails (a model unknown to
  `genai-prices`); the report counts it as unpriced and does not add it to the total.
- A read-only folder or a full disk (a `CostLog` pointed at an unwritable path): the extraction
  still returns its tables and one warning goes to stderr, however many requests there are.
- A failed request (the model raises) writes no record.
- Concurrent writes: many tasks writing at once leave every line parseable and the count exact.
- The record contains no prompt text, no answer and no path (check the keys and that a
  distinctive prompt string is absent from the file).
- The request cache key for a fixed request is the same before and after this change (compare to
  a value computed on `main`).
- The cost history survives clearing the cache: after a run, delete `.quotable/cache/`; the
  report is unchanged. A `cache_dir` passed by the caller gets no cost file inside it, and the
  costs still land in `.quotable/cost/requests.jsonl`.
- Folder layout (existing cache tests updated for the new default folder): the default cache is
  `.quotable/cache/`; `.quotable/.gitignore` is written when quotable creates `.quotable/`; a
  named `cache_dir` is used as given. The move: a `.quotable/` holding loose `<hash>.json`
  files and `ocr/` ends with them under `cache/` and the next run is all cache hits (no model
  request); other entries in `.quotable/` (`cost/`, `.gitignore`, anything unrecognised) are
  not moved; a second run does not move anything again; an entry that cannot be moved stays
  and gives one warning.
- `summarize`/`format_report`: totals across several runs and models (the sum of the stored
  per-request costs, nothing repriced); per-model rows sorted by cost; the four-decimal format
  for a small total; the `$X.XX` format for a large one;
  an unpriced-only file; an empty file and a missing folder give the "no cost records" text;
  a damaged line is skipped and reported with its count; a blank line is ignored silently.
- The CLI (`main([...])` in-process): `cost-report` reads `.quotable/cost/requests.jsonl` from the
  current directory (`monkeypatch.chdir`); `--dir` reads another project's folder; the command
  creates nothing (the folder listing is the same before and after); exit codes 0, 0 (no
  records), 1 (unreadable folder), 2 (unknown option).
- `python -m quotable cost-report` and the `quotable` script both run (a subprocess call).
- `quotable.__all__` is unchanged.
- `just check` passes (ruff, ty, the offline suite). The test count in `AGENTS.md` is updated.

Not verifiable offline: that a real provider's usage numbers and `genai-prices`' price for a
real model agree with the provider's bill. The task adds a line to the live test notes: after
one opt-in live run, compare `quotable cost-report` with the provider's dashboard. This is the
only check that the number is right, and it is the user's to run (it spends money).

## Docs

- `README.md`: a short "Cost" section: where costs are kept (`.quotable/cost/requests.jsonl`,
  apart from the cache), `quotable cost-report` and an example output, that cached answers cost
  nothing and are not counted, and that the figure is an estimate. Everywhere the README says
  the cache is `.quotable/`, it now says `.quotable/cache/`, and it shows the `.quotable/`
  layout and how to clear the cache without losing the costs. The "Not carried over yet" list keeps "dollar-based cost caps" and drops the
  CLI line only as far as cost reporting (there is still no extraction CLI or CSV writer).
- `AGENTS.md`: project state (spec 011), the file tree (`costs.py`, `cli.py`, `__main__.py`;
  `cache.py` line), the `quotable` command in the commands list, and the test count. Also
  correct the sentence in `llm.py`'s docstring that says dollar pricing is left out.
- `pyproject.toml`: the `[project.scripts]` entry.
- Status of this spec set to implemented only after the user approves the change.

## Open questions

Resolved by the user: the report does not count cache hits; costs are stored apart from the
cache, in `.quotable/cost/`, with the cache in `.quotable/cache/` (and room for other things in
`.quotable/` later); the report layout is fine; the new `quotable` command is wanted (the
`justfile` is for working on quotable, the command is for its users); the cost of each request
is stored when written, from pydantic-ai's cost tracking, and the report sums it.

None left. Choices the spec made without asking: the cost file is named `requests.jsonl`, and
the existing cache is moved into `.quotable/cache/` once so nobody pays for answers twice.
