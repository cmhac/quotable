# 002 - Page scoring, document verdict and TextLayerError

Spec: `../spec.md` (Requirements 2-5, 7, 8; Design). Depends on: task 001.

## Goal

A new module `src/pdf_table_extract/textcheck.py` that judges `Layer` objects and raises a
clear error. Not wired into the pipeline yet.

## Steps

1. Define `TextLayerError` (in `textcheck.py`) and `PageQuality` (page number, verdict of
   `ok` / `garbled` / `unassessable`, score, letter count).
2. Implement page scoring: mean log-probability per trigram over the page's letter runs, using
   the reference table from task 001. Digits and punctuation are ignored.
3. Module constants, with provisional values until task 003 sets them: `MIN_LETTERS`,
   `GARBLED_SCORE_THRESHOLD`, and `MAX_GARBLED_PAGE_SHARE = 0.10`. They are constants, not
   parameters of any public function.
4. Implement `check_text_layers(layers)`, which takes the pipeline's `dict[int, Layer]` and
   returns the per-page `PageQuality` list, or raises `TextLayerError` when:
   - no page has any words (missing text layer), or
   - garbled pages exceed `MAX_GARBLED_PAGE_SHARE` of the assessable pages.
   A document with text but no assessable pages is accepted.
5. Error message (requirement 7): the reason, affected pages out of assessed pages, the first
   few affected page numbers, a short excerpt of the offending text for garbled pages, and the
   remedy (re-run OCR over the whole document, replacing the existing text layer).
6. Tests in `tests/test_textcheck.py`, building `Layer`s directly or via `make_pdf`:
   ordinary English accepted; random letter strings rejected; digits-only page unassessable;
   no text rejected as missing; share boundary (at the limit accepted, above rejected);
   message contains reason, page numbers and remedy.

## Acceptance

- New tests pass offline; `just check` passes.
- Nothing in `extract.py` changes in this task.
