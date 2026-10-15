# 002 - Recheck defers to the text layer

Status: draft, awaiting review

## Summary

When the recheck sends a flagged cell back to the model, it should show the model the page's
text layer and tell it to copy the text layer's reading, not to re-read the image and defend
its own. The recheck's acceptance rule (keep a change only if grounding of that cell strictly
improves) stays as the guard. The library already treats the text layer as the reference for
verification; this makes the recheck treat it as the reference for correction too.

## Motivation

The first run on an OCR'd copy of the Senate sample (spec 001 follow-up; PaddleOCR text layer)
extracted 124 rows. Grounding flagged 9 payee names as `ungrounded`, and the recheck changed
none of them: the model returned all 9 unchanged. Looking at the page, the OCR spelling is right
and the model's is wrong in every case checked (`BOLIEK` read as `BODLIEK`, `FARAHMAND` as
`FARAMAND`, `LASHAWNDA` as `LASHANDA`). The cause is the recheck prompt, which shows the model
the image and its previous rows but not the text layer, and says "a mismatch does not prove you
were wrong". The model re-reads the same image and returns the same answer.

Offline experiments on that document (scratch script, 3 rechecks each, first pass cached):

| Recheck variant | Names fixed (of 9) |
|---|---|
| Current prompt | 0 |
| Current prompt, 300 dpi image | 3 |
| Softer "prefer the text layer unless the image clearly disagrees", with the text layer shown | 3 |
| Strict "copy the text layer character for character", with the closest matching text per cell | 9 |
| Strict, with the whole page's text layer shown, 150 dpi | 9 |

With the soft wording the model kept its own spelling whenever the image seemed to support it.
Only the strict wording made it defer. Showing the whole page text gave exactly the same 9
fixes as the per-cell match, with no matching code and no risk of a row window clipping wrapped
text.

Decision (user): OCR errors that end up in the output are preferred over model errors. The
text layer wins when the two disagree.

## Requirements

1. **Show the text layer.** Each recheck request includes the page's whole text layer as one
   text part: one visual line per line, top to bottom, words left to right (so the columns of a
   row are on one line). It is the entire page, not only the lines of the flagged rows.
2. **Strict prompt.** `RECHECK_PROMPT` is replaced. It says that the text layer is an OCR of the
   same page and is the reference; that for each listed cell the model must find that cell's text
   in the text layer (same row, same column) and return it copied character for character, with
   its spelling, digits and punctuation; that a disagreement in spelling or characters is not a
   reason to keep its own value, because the text layer is more reliable than its reading of the
   image, especially for unusual names; and that it keeps its own value only when the text layer
   has no text for that cell (missing, or belonging to another cell). No explanations.
3. **Everything else in the request is unchanged.** The page image (150 dpi), the previous
   rows, and the list of flagged cells with the reason for each flag stay as they are.
4. **Acceptance unchanged.** An answer is applied only if it differs from the original, is not
   blank, does not tokenize like the original, and makes grounding of that cell strictly better.
   Answers for unlisted cells are dropped. `Table.proposals` records outcomes as before.
5. **All flagged statuses.** The strict prompt applies to every status the recheck handles
   (`fuzzy`, `misplaced`, `incomplete`, `ungrounded`).
6. **Same public surface.** No new arguments, flags or environment variables; `extract_table`'s
   signature does not change.
7. **Cache.** The request changes, so cached recheck answers from before this spec are not
   reused. First-pass (schema and extract) cache entries are unaffected.

## Design

- `src/pdf_table_extract/text.py`: add `Layer.lines()` (name open) returning the text of each
  visual line in reading order. It uses the same line-grouping rule as `Layer.crop`, factored
  out so the two share it, not copied.
- `src/pdf_table_extract/recheck.py`: replace `RECHECK_PROMPT`; `_request` adds the text part
  `Text layer of the whole page, one visual line per line:\n<lines>` between the previous rows
  and the cell list. `RECHECK_REASONS` is reworded only where it contradicts the new prompt.
- No change to `grounding.py`, `position.py`, `layout.py` or `extract.py`.

## Behaviour to expect (from the experiments)

- Wrong model spellings that the text layer has right are corrected (9 of 9 names).
- Where the text layer is wrong, its error is copied into the output. In the Senate sample the
  OCR reads every thousands comma as a period, and 99 amounts were changed from `68,027.74` to
  `68.027.74`. This is accepted for now.
- Model inventions are removed: in one description the model had added a word (`MEMBER`) that
  the page does not print; the strict recheck dropped it.
- With the strict prompt the model acts mostly as a copier: the result was identical to
  replacing each flagged cell by its closest text-layer match, with no model. The model is kept
  because it also decides when a cell's text is absent or belongs elsewhere, which that
  replacement cannot judge (not exercised in the experiments).

## Limits

- Evidence is one document and one kind of error (OCR spelling vs model spelling). Wrapped
  cells, cells absent from the text layer, and layers with systematic errors other than
  comma/period were not exercised.
- Wrapped cells: the whole-page text shows each visual line, so a cell wrapped over several
  lines appears on several lines interleaved with other columns. The model must stitch it. Not
  tested.
- Request size grows by the page's text (about 350 to 480 words per page in the sample).
  Pages with far more text cost proportionally more per recheck.
- A model that ignores the instruction is still stopped by the acceptance rule, but cannot be
  made to copy.

## Alternatives considered

- **Per-cell closest-match text instead of the whole page.** Same fixes (9 of 9) but needs
  fuzzy matching code and fails if the match is on another line; rejected for the whole page.
- **Row windows of text-layer text** (the original project's approach). Rejected because a
  window that clips wrapped text omits part of the cell.
- **Deterministic replacement with no model.** Identical result on this sample, but cannot
  judge missing or misplaced text; not chosen.
- **Higher-resolution recheck image.** Fixed 3 of 9; not needed once the text layer is shown.

## Out of scope

- Changing the first-pass extraction prompts, the DPI, or the grounding and position rules.
- Normalising punctuation lookalikes (comma/period) in grounding.
- Multiple tables per page and parent/child context across pages (separate specs).
- Running OCR in this library.

## Tests

All offline, no network.

- A recheck request includes a text part with the page's whole text layer, one line per visual
  line, in reading order (synthetic PDF built with `make_pdf`; assert on the part's text, not
  only that it exists). Words from rows that were not flagged are present too.
- The recheck prompt states that the text layer is the reference and that spelling disagreement
  is not a reason to keep the model's value (assert on key phrases).
- The existing recheck tests still pass unchanged: accepted when grounding improves, original
  kept when it does not, blank ignored, same-token answer not applied, unlisted cells ignored,
  clean document never rechecked.
- `Layer.lines()`: words on one visual line are joined left to right; lines come top to
  bottom; a rotated page reads in upright order (reuse an existing rotated fixture).
- Existing tests that assert on the recheck request parts are updated for the new part.
- Manual check, not part of CI (needs a model, so only with explicit go-ahead): rerun the
  OCR'd Senate sample and confirm the 9 payee names end `exact`, with the request count
  recorded. The OCR'd PDF is `tests/data/senate_expenditures_paddleocr.pdf`.

## Docs

- `README.md`: the Recheck row says the model is shown the page's text layer and told to
  copy it, so text-layer errors can pass into the output.
- `AGENTS.md`: update project state and the test count.
- `recheck.py` module docstring: replace "sending the text-layer text of each flagged row" in
  the list of things left out, since the whole page text is now sent.

## Open questions

1. Size cap on the text sent. This spec sends the whole page with no cap, because truncating
   brings back the omitted-text problem. A very dense page could be large. Say if you want a
   cap (for example a character limit, with the page split over several requests when it is
   exceeded), or if no cap is fine for now.
2. Resolved (user): all four flagged statuses use the strict prompt (requirement 5).
3. Resolved (user): both versions of the Senate document are committed fixtures,
   `senate_expenditures_garbled.pdf` and `senate_expenditures_paddleocr.pdf`, for different
   test purposes. The OCR'd one is now in `tests/data/` (1.2 MB). Replaying it offline would
   still need recorded model answers (`.rows.json`); not part of this spec unless asked.
