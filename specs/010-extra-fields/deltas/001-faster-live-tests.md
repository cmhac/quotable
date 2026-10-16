# 001 - Faster live tests

Delta to: ../spec.md (the live tests under "Tests", task 012). Requested after the first live run
looked too slow: about 700 to 800 new requests, run one test at a time, estimated at 45 to 60
minutes (an estimate; no request time was measured).

## Change

1. **Parallel runs.** `pytest-xdist==3.8.0` joins the dev dependency group. The live cases are
   independent: each writes to its own cache directory (`.cache/extra/<kind>/<case>/run<N>`) and
   its own `report-<case>-run<N>.json`. Run them with `just test-live -n 4 <file>`. `-n` is not
   in `addopts`, so the offline suite is unchanged.
2. **Run count.** `QUOTABLE_LIVE_RUNS` (default 3, a positive whole number; anything else raises
   `ValueError`) sets how many times each case runs. `1` is the cheap first look; it cannot show
   run-to-run differences, so the default stays 3. Parsing is `live_runs()` in
   `tests/extra_fields_live.py`, tested offline.
3. **Progress lines under `-n`.** Each line names its worker (`[live 02:14 gw1]`) and the request
   count is per worker. Checked with a probe run under `-n 2` with default capture and no `-s`:
   the lines reached stderr.
4. **`just test-live`** takes pytest arguments, like `just test`.

## Not changed

- The library's `MAX_CONCURRENT_REQUESTS = 4` and discovery's one-window-after-another order.
- The regression test still uses separate caches for the runs with and without extra fields.
  Sharing extraction answers between them was proposed and not chosen.

## Risks

- Each worker keeps up to 4 requests in flight, so `-n 4` can mean 16 at once. The library has no
  retry for rate-limit errors of its own; whether the provider SDK retries them was not checked.
  A rate-limit failure would show as a failed test, not a wrong answer. Lower `-n` if it happens.
- Worker request counters are separate, so the "model request N" numbers are not a global total.

## Done when

- `live_runs` tests pass (red first, then green), `ruff`, `ty` and `just test` pass.
- `pytest -m live --collect-only` lists 3 runs per case by default and 1 with
  `QUOTABLE_LIVE_RUNS=1`.
- No live test was run.
