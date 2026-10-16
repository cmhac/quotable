# 012 - Live tests (written here, run only with the user's go-ahead)

Spec: `../spec.md` (Tests / Live; Requirement 21). Depends on: task 010.

## Goal

The live tests exist and are collected but deselected; the user decides if and when they run.

## Steps

1. Read `tests/live/test_live_merge.py` first; follow its markers, skip rules, the three runs per
   case in separate cache directories, and how it reports numbers.
2. New `tests/live/test_live_extra_fields.py` with three groups of tests:
   - Regression: for the Senate sample and a chosen set of the spec 007 documents, discovery with and
     without `extra_fields` gives the same tables (columns, pages, rows after extraction). Any
     difference is reported as a finding, not loosened.
   - Fixture accuracy: for the `extra-*` documents, per page and field: printed value equals the
     truth, carried value and `source_page` equal the truth (set `carry_forward=True` explicitly),
     no missed header remains after the second look, no invented value; `expect_stale` and
     `expect_blind` documents are reported, not asserted. Report: missed headers before and after
     the region check, false alarms, second-look requests per 100 pages.
   - Real slice: 60 consecutive pages of the full report from `QUOTABLE_LIVE_EXTRA_PDF`, with the
     section starts known from the pages whose layer contains `QUOTABLE_LIVE_EXTRA_LABEL`. Skipped
     when either variable is unset. The file is not committed.
3. Add the two variables to `.env.example` (names only, no values) and to `tests/data/README.md`.
4. Confirm the tests are collected and deselected by default (`just test --collect-only -m live`
   style check) and skip cleanly with no key. **Do not run them.** Running costs money and needs the
   user's explicit go-ahead and a budget; ask first, with an estimate of the request count (windows
   plus second looks, three runs per case).
5. `ruff check`, `ruff format`, `ty check`, `just test`.

## Done when

The live tests are collected, deselected, skip without a key, and the checks are clean. Any run
results are recorded in the spec only after the user approves a run.
