# 005 - The review queue, sampling and statistics

Spec: `../spec.md` (Requirements D1, D2, D3, E). Depends on: tasks 002 and 004.

## Goal

`quotable/review/queue.py`: pure functions that build the population of a queue from runs,
draw the sample, and compute every number of section E. Standard library only (`random`,
`statistics.NormalDist`, `math`).

## Decisions made here

- **"All runs"** means the newest run of each document, so a re-run does not count the same
  cells twice.
- The population is sorted by (document name, run id, table index, page, row, column order,
  extra fields last) before sampling, and the queue keeps that order, so a reviewer moves down
  the pages rather than jumping about. Order does not change the statistics.
- An extra field is one population item per (printing page, name) of a run (D9), with the
  status of the printed value.

## Steps

1. Red first: tests in `tests/review/test_queue.py` (step 4).
2. `queue.py`:
   - `QueueSettings` (frozen dataclass): statuses, run id or all, table index or all, column or
     all, include extra fields, mode (`all | sample`), sample size, confidence (80, 90, 95,
     99), target margin in points, seed. `from_query` / `to_dict` for the app and the verdict
     line (F2).
   - `population(runs, settings) -> list[Item]` and `counts_by_status(...)` (the numbers next
     to each status check box, D1).
   - `sample(items, settings) -> list[Item]`: all items, or
     `random.Random(seed).sample(items, n)` re-sorted into population order; `n` is capped at
     the population.
   - `z(confidence)`: `NormalDist().inv_cdf(1 - (1 - c) / 2)`.
   - `suggested_size(target, confidence, population)`: $n_0 = z^2 \cdot 0.25 / e^2$, then
     $n_0 / (1 + (n_0 - 1)/N)$, rounded up (D2).
   - `statistics(queue, verdicts, settings) -> Stats`: population, sample, reviewed, judged,
     can't tell, changed, share, Wilson interval, estimated wrong cells with interval, margin
     before ($p = 0.5$, $n$ = sample) and so far ($p$ = share, $n$ = judged), each with its
     finite-population correction $\sqrt{(N - n)/(N - 1)}$ (0 when $n = N$; no division by
     zero when $N = 1$ or nothing is judged), the by-status table with its "All" line, and
     error-category counts, most first. A stale verdict does not count (D8).
3. Every number is returned as a float or int; formatting is the browser's job.
4. Tests:
   - the mockup's numbers: 6 changed of 35 judged, 2 can't tell, $N = 1846$, $n = 120$,
     95%: share 17.1%, Wilson 8.1-32.7%, estimated 316 (150-603), margin before 8.7 points
     (correction 0.967), so far 12.4 points (correction 0.991), target 8 points suggests 139;
   - the four `z` values; nothing judged; $n = N$; $N = 1$;
   - the same seed and settings give the same queue, another seed another one; the sample is
     a subset in population order;
   - "All runs" takes the newest run of each document; scope by table and column; extra fields
     in and out; `exact` added only when chosen;
   - by-status and categories add up to the totals.
5. `ruff check`, `ruff format`, `ty check`, `just test`.

## Done when

The mockup's figures come out of the functions, sampling is reproducible, and the suite passes.
