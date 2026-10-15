# 008 - Live check on the OCR'd Senate PDF

Spec: `../spec.md` (Tests, live test and manual check). Depends on: 005, 007.
Needs a model, so only with the user's explicit go-ahead; nothing is run without it.

## Steps

1. Ask the user for the go-ahead and a request cap (the manual runs used 1 discovery request,
   4 extract requests and 3 to 6 recheck requests).
2. Run `extract_tables` on `tests/data/senate_expenditures_paddleocr.pdf` with a fresh cache
   under `$KIROCREW_SCRATCH` and the cap.
3. Report: the number of tables; rows per page of each; cell statuses and the position-check
   counts per table; recheck outcomes; new requests used.
4. Expected from the manual runs: two tables; summary 7 rows (17 exact, 11 empty); detail 36,
   62 and 26 rows, about 370 exact cells, 0 or 1 misplaced. Report differences; do not adjust
   the spec or tests to match.

## Acceptance

- The report is in the reply. Nothing in the repository changes unless the user asks.
