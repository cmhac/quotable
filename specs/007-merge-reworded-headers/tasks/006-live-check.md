# 006 - Live check with the real model

Spec: `../spec.md` (Tests, live; Motivation). Depends on: task 005. Costs money: do not run
without the user's go-ahead.

## Goal

Show, with the real model, that the defect from the Motivation is fixed and that the cases that
were already right are unchanged.

## Steps

1. `tests/live/test_live_merge.py`, opt-in like the existing live test (`pytest.mark.live`,
   skipped without `OPENAI_API_KEY` and `GRIDKEY_LIVE_TEST_MODEL`, answers cached under
   `tests/live/.cache`, `max_requests` capped). Documents are the fixture's "Pipeline" and
   "Controls" families, read from `tests/data/synthetic/` with their truth files; the
   assertions compare the returned tables with the truth rows (row values, page numbers,
   number of tables), not with a stored model answer.
2. Cases:
   - `pipe-reworded-gap{0,1,4,9,20}`, `pipe-reworded-headerless`, `pipe-reworded-lookalike`,
     `pipe-long-parts`: one `Table`, all truth rows present, `merged` has one entry. (A case
     where the real model reports the second part's header in a way the rules rightly refuse
     is a finding, not a test to loosen: report it.)
   - `pipe-exact-gap*`, `pipe-caps`, `ctrl-single-table`: one `Table`, `merged == ()` (the
     headers already match; the new step must not act).
   - `ctrl-unrelated`: two `Table`s, `merged == ()` on both.
   - Each case also runs with `merge_reworded=False`; the reworded ones then give two `Table`s.
3. The earlier ad-hoc live cases (`caps_reworded`, `multilevel_gap`, `headerless_long_gap`,
   `caps_flat_drift`, `interleaved_two_tables`, `lookalike_prose_gap`, `long_gap_20`; the
   scratch harness that held them is gone): map each to a fixture document. `caps_reworded`,
   `headerless_long_gap`, `lookalike_prose_gap` and `long_gap_20` have counterparts in the list
   above. For `multilevel_gap`, `caps_flat_drift` and `interleaved_two_tables`, add a document
   to the "Pipeline" family in `tests/synthetic_cases.py` if the generator can express it
   (then regenerate with `just synthetic`, and the fixture-integrity tests must still pass);
   if it cannot, say which and why in the report and do not claim the coverage.
4. Run 3 times per case, only after the user says go. Report per case: tables returned, merged
   or not, rows exact, requests used, cost if the run reports it. Compare with the 3-of-3
   split recorded in the Motivation.
5. Record the outcome in the spec ("Results" under Tests), including any case that behaves
   differently from the offline expectation.

## Done when

The user has the per-case table; the reworded cases come back as one `Table` on every run or the
exceptions are explained; the unchanged cases are unchanged; no live test runs by default
(`just test` still deselects them).
