# 002 - The cost record and the cost log

Spec: `../spec.md` (Requirements 1, 3, 5, 7, 8; Design / Code; Tests). Depends on: task 001.

## Goal

A `CostLog` appends one JSON line per paid request to `.quotable/cost/requests.jsonl`, safely,
and can never raise into the caller. Nothing calls it yet (task 004).

## Steps

1. Red first: a new `tests/test_costs.py` with the tests below, failing.
2. New `src/quotable/costs.py`. It imports the standard library and `quotable.cache` only, no
   pydantic-ai, pandas or PyMuPDF (the report command in task 005 depends on that).
3. `CostRecord`: frozen dataclass with the spec's fields in the spec's order (`v`=1, `time`,
   `run`, `stage`, `model`, `input_tokens`, `output_tokens`, `cache_read_tokens`,
   `cache_write_tokens`, `cost_usd: float | None`). `to_line()` returns compact JSON plus `"\n"`.
   `from_line(line)` raises `ValueError` for bad JSON, a non-object, a missing field, a wrong
   type (a `bool` is not an `int`) or `v != 1`. `cost_usd` is written as a JSON number from the
   `Decimal` price (`float(price)`); task 003 reads it back through `Decimal(str(value))`, so
   sums do not drift.
4. `CostLog(run_id: str | None = None)`: `run_id` defaults to `uuid4().hex`.
   `record(stage, model, *, input_tokens, output_tokens, cache_read_tokens, cache_write_tokens,
   cost: Decimal | None)` builds the record (`time` is `datetime.now(UTC).isoformat(timespec=
   "seconds")`) and appends it. Plain values rather than a pydantic-ai usage object keep this
   module light; task 004 maps one onto the other. The folder is found at the first record with
   `resolve_project_dir()` (task 001) plus `cost/`, so a run that never pays creates nothing.
   Append with `os.open(path, O_WRONLY | O_APPEND | O_CREAT, 0o644)` and one `os.write` of the
   whole encoded line, then close: no `open()` buffering, no lock file (Requirement 8).
5. Failures: `record` catches `OSError` (including from `resolve_project_dir`) and calls a
   private `_warn_once(message)` that prints to stderr the first time only. A second public
   method, `skip(reason)`, goes through the same `_warn_once` (task 004 uses it when a model
   reports no usage), so one run warns at most once whatever the cause. Neither method raises.
6. Tests (all offline, no model): a record has exactly the spec's keys and the values passed
   in; `to_line`/`from_line` round-trip, and each malformed input raises `ValueError`; the
   file and `.quotable/.gitignore` appear on the first record and not before; an existing
   `.quotable/` gets no `.gitignore`; two `CostLog`s in one folder write distinct `run` ids and
   one `CostLog`'s records share theirs; `cost=None` writes `"cost_usd": null` with the tokens
   kept; no prompt, answer or path can get in (the keys are fixed, and a distinctive string
   passed as `model` is the only free text); an unwritable folder (read-only `.quotable/cost`
   or a file where the folder should be) gives exactly one stderr line across many `record`
   calls, and `skip` after it adds none; 200 concurrent `record` calls through
   `asyncio.gather` and two `CostLog`s writing from separate threads leave every line
   parseable and the count exact.
7. `ruff check`, `ruff format`, `ty check`, `just test`.

## Done when

The new tests pass, the existing suite passes unchanged, and `ty` and `ruff` are clean.
`costs.py` has no import outside the standard library and `quotable.cache`.
