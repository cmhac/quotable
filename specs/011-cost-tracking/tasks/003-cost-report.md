# 003 - Summing the log and formatting the report

Spec: `../spec.md` (Requirements 4, 5, 6, 10; Tests / `summarize`/`format_report`). Depends on: task 002.

## Goal

Two pure functions turn a cost file into the report text. No terminal, no command yet.

## Steps

1. Red first: report tests added to `tests/test_costs.py`, failing.
2. `costs.py`: `ModelTotals` and `CostSummary` frozen dataclasses. `CostSummary` holds `runs`
   (distinct `run` ids), `requests` (every record), `unpriced` (records with `cost_usd` null,
   a subset of `requests`), `input_tokens`, `output_tokens`, `total: Decimal`, `models`
   (a tuple of `ModelTotals`: model, requests, input, output, cost, sorted by cost descending,
   ties by name) and `skipped` (unreadable lines).
3. `summarize(path: Path) -> CostSummary` reads the file line by line. A missing file gives an
   empty summary (not an error). A blank line is ignored silently. A line `from_line` rejects
   adds one to `skipped`. The total is the sum of the stored `cost_usd` values as
   `Decimal(str(value))`; nothing is repriced. Any `OSError` other than "file not found" (a
   directory in the way, no permission) propagates unchanged, so task 005 can exit 1 naming
   the path.
4. `format_report(summary, path: Path) -> str`, plain text, no colour, laid out like the
   spec's example: `Cost report for <path>` (relative to the working directory when inside it),
   a blank line, `Runs:`, `Requests:  N paid, M unpriced` (N counts every request that reached
   the model and M is how many of those had no price), `Tokens:  X in, Y out`, `Total:`, a
   blank line, then the `By model` table with columns aligned from the data and thousands
   separators. Money is in US dollars, rounded half up, with one precision for the whole
   report chosen by the total: two decimals when the total is at least $1, otherwise four (so
   the rows and the total agree). When `unpriced` is above zero add one line under the table:
   `Total leaves out N unpriced requests.` When `skipped` is above zero end with
   `Skipped N unreadable lines.` (singular for 1).
5. No records (`requests == 0` and `skipped == 0`): the whole output is
   `No cost records found in <path>. Costs are recorded when quotable sends a request to a
   model.` as one line. A file with only unreadable lines is not "no records": it prints the
   zero report and the skipped line.
6. Tests: totals over several runs and models, checked against a hand sum (and against a case
   where float addition would drift, such as many `0.1` costs); model rows sorted by cost;
   `$X.XX` for a total of exactly 1.00 and above, four decimals for 0.9999 and below;
   unpriced-only file (total 0, line about unpriced); a missing file and an empty file give the
   no-records text; a damaged line is counted and the others still sum; a blank line is not
   counted; `summarize` on a directory raises `OSError`; the exact text of the example in the
   spec for a small hand-built file.
7. `ruff check`, `ruff format`, `ty check`, `just test`.

## Done when

The new tests pass, the existing suite passes unchanged, and `ty` and `ruff` are clean. The
imports of `costs.py` are still the standard library and `quotable.cache` only.
