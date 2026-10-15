# 003 - Check the change on the OCR'd Senate document

Spec: `../spec.md` (Tests, manual check). Depends on: task 002.

## Goal

Confirm on the real document that the strict recheck fixes the misread names, and record what
it cost. This needs a real model, so it runs only with the user's explicit go-ahead.

## Steps

1. Ask the user for the go-ahead before any live request, and state the request cap (the first
   pass is cached in the scratch `cache_ocr` directory, so only the 3 rechecks should be new; set
   `max_requests` to 6).
2. With the go-ahead, run `extract_table` on `tests/data/senate_expenditures_paddleocr.pdf`
   with a `CachedClient` over a fresh scratch cache, from a script in `$KIROCREW_SCRATCH`
   (nothing added to the repo).
3. Report, per column, the cell grounding counts; the 9 payee cells that were flagged before
   (`CURTIN, MARESA A`, `DUDLEY, DRENAH ELIZABETH`, `ELSEN, JEAN TOAL`, `FRIEND, LAURA A`,
   `WALGREEN, HOWARD L`, `SMITH, LASHANDA M`, `BODLIEK, SARAH W`, `SHAHMORADI, HEIDER R`,
   `FARAMAND, KALI A`) and what each became; the number of new model requests; and any proposal
   that was `not_improved`.
4. If any of the 9 names does not end `exact`, stop and report instead of changing the prompt
   to fit.

## Acceptance

- The 9 payee names end `exact` with the text layer's spelling, using only recheck requests.
- The report states the request count and lists any side effects (changed amounts or
  descriptions) as the experiments did.
- No files in the repo change in this task.
