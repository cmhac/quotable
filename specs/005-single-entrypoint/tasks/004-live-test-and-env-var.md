# 004 - Live test and the renamed test variable

Spec: `../spec.md` (Requirement 9; Open question 2). Depends on: task 002.

## Goal

The live test uses the public function and reads `GRIDKEY_LIVE_TEST_MODEL`.

## Steps

1. `tests/live/test_live_extraction.py`: read `GRIDKEY_LIVE_TEST_MODEL`; call
   `extract_tables(DATA / f"{name}.pdf", model=MODEL, cache_dir=CACHE / name,
   max_requests=MAX_NEW_REQUESTS)`; update the docstring and the skip message. It still skips
   unless the variable and `OPENAI_API_KEY` are both set.
2. Replace `GRIDKEY_LIVE_MODEL` with `GRIDKEY_LIVE_TEST_MODEL` in `justfile`, `.env.example`,
   `README.md` and `AGENTS.md`. No fallback to the old name. Do not read or edit `.env`; tell the
   user to rename the key there.
3. Do NOT run `just test-live` (costs money; needs the user's go-ahead).

## Done when

`just test -m live` collects the live test and skips it with the new message when the variable is
unset, and `grep -r GRIDKEY_LIVE_MODEL` finds nothing outside `specs/003-*` and `specs/005-*`.
