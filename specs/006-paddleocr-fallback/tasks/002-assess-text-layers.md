# 002 - `assess_text_layers`: which pages failed?

Spec: `../spec.md` (Requirements 1, 2; Design / Flow). Depends on: nothing.

## Goal

`textcheck.py` can say which pages are bad without raising, so the pipeline can OCR exactly
those pages. `check_text_layers` behaves exactly as before.

## Steps

1. `textcheck.py`: add a frozen dataclass `Assessment` with the per-page `PageQuality` list, the
   rejection reason (`str | None`, the text `check_text_layers` raises today) and
   `bad_pages: tuple[int, ...]` (page numbers as `PageQuality` already numbers them: pages
   judged garbled plus pages with no words, in page order).
2. Add `assess_text_layers(layers) -> Assessment` holding the logic now inside
   `check_text_layers`. `check_text_layers` calls it and raises `TextLayerError` with the same
   message when `reason` is not `None`. Thresholds (`MIN_LETTERS`, `GARBLED_SCORE_THRESHOLD`,
   `MAX_GARBLED_PAGE_SHARE`) and the trigram scoring do not change.
3. Leave `REMEDY` and the `TextLayerError` message as they are; task 009 rewrites them.
4. Tests in `tests/test_textcheck.py`: `bad_pages` is the garbled plus the empty pages for a
   mixed document; empty for an accepted document; for a document rejected only because no page
   has words, every page is bad. The existing textcheck and calibration tests pass unchanged.
5. `ruff check`, `ruff format`, `ty check`, `just test`.

## Done when

The new tests pass, no existing test was edited, and `check_text_layers` raises the same
messages as before.
