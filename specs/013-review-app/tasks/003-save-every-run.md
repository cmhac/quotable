# 003 - `extract_tables` saves every run

Spec: `../spec.md` (Requirements A1, A3, A4, A6). Depends on: task 002.

## Goal

Every call of `extract_tables` / `extract_tables_async` that returns writes its run to the
project's `.quotable/runs/<run id>/`, with the run id of the cost log. A call that raises writes
nothing, and a write that fails only warns.

## Steps

1. Before editing: compute `request_key` for a fixed request with the current code and keep the
   literal in a test, as spec 011 task 004 did; it must still pass at the end (A6).
2. Red first: the tests of step 6.
3. `pipeline.py`: `run_pipeline` takes an optional keyword `trace: RunTrace | None = None`, a
   small internal dataclass it fills when given: the full page layers after OCR (`layers`), the
   discovered tables' `(label, first row, last row)` per page (what `table_page_layers` already
   uses) and the OCR'd pages. Its return value and every existing caller are unchanged.
4. `steps/layout.py`: split the band computation out of `table_layers` into a function that
   returns the `(top, bottom)` of each table on a shared page; `table_layers` calls it, so
   behaviour is unchanged. Headers for the run come from `find_header(columns, layer)` on the
   full page layer, as `page_layouts` does.
5. `extract_tables_async`: record the start time, build `CostLog()` as today and use its
   `run_id`; after `run_pipeline` returns, compute the document fields (SHA-256 read in chunks,
   size, page count and page sizes with `pymupdf`), the model name with `model_name(model)`,
   the version with `importlib.metadata.version("quotable")`, the settings, the bands and the
   headers, and call `write_run`. Wrap all of it: an `OSError` (or any exception from the
   saving code) prints one line to stderr (`quotable: could not save the run to <path>:
<reason>`) and the tables are returned as usual. The project folder is
   `resolve_project_dir()`, never `cache_dir`. One sentence in the docstring.
6. Tests (offline, `Calls` from `tests/test_entrypoint.py`, in a temporary working directory):
   - one run folder after `extract_tables`, its id equal to the `run` field of the cost
     records it wrote; a second call (all cache hits) adds a second run folder and no cost
     record;
   - `cache_dir=tmp_path/"named"`: the run is under the working directory's
     `.quotable/runs/`, nothing run-related inside `named`;
   - `BudgetExceededError` (`max_requests=1`) and `TextLayerError` (a garbled fixture with
     `ocr=False`): no `runs/` entry at all;
   - an unwritable `.quotable/runs` (monkeypatch `write_run` to raise `OSError`): the tables
     are returned and stderr holds one warning;
   - the document fields (SHA-256 of the fixture file, size, pages) and settings are right;
   - the cache-key literal of step 1; `quotable.__all__` unchanged.
7. `ruff check`, `ruff format`, `ty check`, `just test`.

## Done when

Each successful call leaves exactly one complete run, a failed call none, the existing suite
passes unchanged, and `ty` and `ruff` are clean.
